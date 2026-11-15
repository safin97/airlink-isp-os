from datetime import timedelta
from airlink import deye_grid, deye
from airlink.db import SessionLocal
from airlink.models import DeyeConnection, DeyeGridHistory, now
from test_deye import cloud, CONFIG, PATH


def device_sample(stamp, volts=(230,), state=1, unit='V'):
    return {'deviceDataList': [{'deviceSn': 'inverter-test', 'deviceState': state,
            'collectionTime': stamp.timestamp(), 'dataList': [
                {'key': ['GridVoltageL1', 'GridVoltageL2', 'GridVoltageL3'][i], 'unit': unit, 'value': value}
                for i, value in enumerate(volts)]}]}


def test_grid_voltage_estimate_never_uses_zero_power_or_cloud_offline_as_outage():
    stamp = now()
    def reading(volts=(230,), state=1, unit='V', time=stamp):
        return deye_grid.from_devices(device_sample(time, volts, state, unit), ['inverter-test'], stamp)
    assert reading()['state'] == 'up'
    assert reading((0,))['state'] == 'down'
    for sample in [reading((0,), state=3), reading((230,), state=True), reading((230, 0)), reading((30,)), reading(('NaN',)),
                   reading((230,), unit='W'), reading((230,), time=stamp - timedelta(minutes=16))]:
        assert sample['state'] == 'unknown'
    assert deye_grid.from_devices({'gridPower': 0}, ['inverter-test'], stamp)['state'] == 'unknown'
    assert reading((.230,), unit='kV')['state'] == 'up'


def test_observed_grid_time_deduplicates_samples_and_excludes_closed_page_gaps(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    base = now()
    with SessionLocal() as db:
        uid = db.query(DeyeConnection).one().user_id
        def record(seconds, state='up', sample_seconds=None):
            current = base + timedelta(seconds=seconds)
            sample = base + timedelta(seconds=seconds if sample_seconds is None else sample_seconds)
            result = deye_grid.record(db, uid, '123', {'state': state, 'observed_at': sample.isoformat(), 'voltages_v': [230 if state == 'up' else 0]}, current)
            db.commit()
            return result
        assert record(0)['uptime_seconds'] == 0
        assert record(30, sample_seconds=0)['uptime_seconds'] == 0
        assert record(60)['uptime_seconds'] == 60
        assert record(90, 'down')['downtime_seconds'] == 0  # Transition timing is unknown.
        assert record(120, 'down')['downtime_seconds'] == 30
        assert record(400, 'down')['downtime_seconds'] == 30  # No backfill while closed.
        assert record(430, 'down', 400)['downtime_seconds'] == 30
        result = record(460, 'down')
        assert result['downtime_seconds'] == 90 and result['uptime_seconds'] == 60
        assert result['unknown_seconds'] == 310
        assert deye_grid.public(db.get(DeyeGridHistory, (uid, '123')).history, base + timedelta(seconds=1600))['state'] == 'unknown'
        assert db.get(DeyeGridHistory, (uid, '999')) is None
    # Same-account reconnect preserves totals; changing the cloud account clears them.
    client.put(PATH, headers=owner, json=CONFIG)
    with SessionLocal() as db:
        assert db.query(DeyeGridHistory).count() == 1
    client.put(PATH, headers=owner, json={**CONFIG, 'account': 'other@example.invalid'})
    with SessionLocal() as db:
        assert db.query(DeyeGridHistory).count() == 0


def test_grid_api_uses_device_inventory_and_preserves_station_readings_when_device_access_fails(client, owner, cloud, monkeypatch):
    original = deye.request
    calls = []
    fail = False
    def request(region, path, body, **kwargs):
        calls.append((path, body))
        if path == '/station/device':
            return {'success': True, 'deviceListItems': [{'stationId': 123, 'deviceType': 'INVERTER', 'deviceSn': 'inverter-test'}], 'total': 1}
        if path == '/device/latest':
            if fail:
                from fastapi import HTTPException
                raise HTTPException(502, 'Vendor secret must not escape')
            return {'success': True, **device_sample(now())}
        return original(region, path, body, **kwargs)
    monkeypatch.setattr(deye, 'request', request)
    client.put(PATH, headers=owner, json=CONFIG)
    result = client.get(PATH + '/stations/123/latest', headers=owner).json()
    assert result['solar_w'] == 4200 and result['grid_availability']['state'] == 'up'
    assert ('/device/latest', {'deviceList': ['inverter-test'], 'deviceType': 'INVERTER'}) in calls
    assert 'inverter-test' not in str(result)
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        row.cache = {**row.cache, 'readings': {'123': {**row.cache['readings']['123'], 'at': 0}}}
        db.commit()
    fail = True
    result = client.get(PATH + '/stations/123/latest', headers=owner).json()
    assert result['solar_w'] == 4200 and result['grid_availability']['state'] == 'unknown'
    assert 'Vendor secret' not in str(result)
    assert len([c for c in calls if c[0] == '/station/device']) == 1
    assert client.delete(PATH, headers=owner).status_code == 200
    with SessionLocal() as db:
        assert db.query(DeyeGridHistory).count() == 0


def test_duplicate_sample_after_a_gap_cannot_backfill_the_gap(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    base = now()
    with SessionLocal() as db:
        uid = db.query(DeyeConnection).one().user_id
        for poll, sample, expected in [(0, 0, 0), (30, 0, 0), (300, 0, 0), (330, 330, 0), (360, 360, 30)]:
            result = deye_grid.record(db, uid, '123', {'state': 'up', 'observed_at': (base + timedelta(seconds=sample)).isoformat()},
                                      base + timedelta(seconds=poll))
            db.commit()
            assert result['uptime_seconds'] == expected
        assert result['unknown_seconds'] == 330


def test_grid_history_migration_keeps_connection_data(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = create_engine('sqlite:///' + str(tmp_path / 'grid-migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE deye_connections (user_id VARCHAR(36) PRIMARY KEY, encrypted_credentials TEXT)'))
        connection.execute(text("INSERT INTO deye_connections VALUES ('owner', 'preserved')"))
        spec = importlib.util.spec_from_file_location('grid_history_migration', Path(__file__).resolve().parents[1] /
                                                     'database/versions/a27bf694085e_deye_grid_history.py')
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert 'deye_grid_history' in inspect(connection).get_table_names()
        migration.downgrade()
        assert connection.execute(text('SELECT encrypted_credentials FROM deye_connections')).scalar() == 'preserved'
    engine.dispose()
