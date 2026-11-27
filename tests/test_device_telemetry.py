import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import pytest
from sqlalchemy import select, delete

from airlink import api
from airlink.db import SessionLocal
from airlink.models import Device, DeviceTelemetrySnapshot, Metric, now
from monitoring import worker
from test_api import device
from test_tower_api import settings


def test_last_readings_survive_outage_retention_and_refresh_on_recovery(client, owner, monkeypatch):
    tid = client.post('/api/towers', headers=owner, json=settings()).json()['id']
    did = device(client, owner, tid)
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=False))
    readings = {'wireless_ssids': ['North'], 'wireless_clients': 12,
                'uptime_seconds': 90060, 'signal_dbm': -62,
                'ethernet_links': [{'name': 'ether1', 'speed_mbps': 1000}]}
    probe = AsyncMock(return_value=readings)
    monkeypatch.setattr(worker, 'collect_api', probe)
    clock = now()
    monkeypatch.setattr(worker, 'now', lambda: clock)
    monkeypatch.setattr(api, 'now', lambda: clock)

    def poll():
        async def run():
            await worker.poll(did, asyncio.Semaphore(1))
        asyncio.run(run())

    def row():
        return client.get('/api/devices', headers=owner).json()[0]

    assert row()['telemetry'] == {'ethernet_links': []}
    poll()
    first = row()
    assert first['telemetry'] == readings and first['telemetry_stale_fields'] == []
    stamp = first['telemetry_at']
    probe.side_effect = RuntimeError('unreachable')
    for _ in range(3):
        clock += timedelta(minutes=1)
        poll()
    down = row()
    assert down['status'] == 'offline' and down['downtime_seconds'] == 120
    assert down['telemetry'] == readings and down['telemetry_at'] == stamp
    assert set(down['telemetry_stale_fields']) == set(readings)
    with SessionLocal() as db:
        latest = db.scalar(select(Metric).where(Metric.device_id == did).order_by(Metric.id.desc()))
        # Last known values must never become new monitoring/chart/alert samples.
        assert latest.values['api_up'] is False and 'uptime_seconds' not in latest.values
        db.execute(delete(Metric).where(Metric.device_id == did))
        db.commit()
    # Separate API requests/DB sessions retain the snapshot even after raw samples expire.
    clock += timedelta(days=31)
    assert row()['telemetry'] == readings
    assert row()['downtime_seconds'] is None  # Monitoring gaps aren't confirmed downtime.
    poll()
    assert row()['telemetry'] == readings

    # A partial success changes only supplied fields; zero is a genuine new reading.
    probe.side_effect = None
    probe.return_value = {'wireless_clients': 0, 'signal_dbm': -70, 'uptime_seconds': 30}
    clock += timedelta(minutes=1)
    poll()
    recovered = row()
    assert recovered['status'] == 'online' and recovered['downtime_seconds'] is None
    assert recovered['telemetry'] == {**readings, **probe.return_value}
    assert set(recovered['telemetry_stale_fields']) == {'wireless_ssids', 'ethernet_links'}
    assert recovered['telemetry_field_times']['wireless_ssids'] == stamp
    assert recovered['telemetry_field_times']['uptime_seconds'] == clock.isoformat()

    # Editing a device keeps its display history, but never calls it a live reading
    # from the new address. Live monitoring restarts independently.
    changed = client.put('/api/devices/' + did, headers=owner, json={
        'tower_id': tid, 'name': 'New target', 'ip_address': '192.0.2.99'})
    assert changed.status_code == 200
    pending = row()
    assert pending['telemetry'] == recovered['telemetry']
    assert set(pending['telemetry_stale_fields']) == set(recovered['telemetry'])
    assert pending['telemetry_field_addresses']['uptime_seconds'] == '192.0.2.1'
    probe.side_effect = RuntimeError('unreachable')
    clock += timedelta(minutes=1)
    poll()
    assert row()['telemetry'] == recovered['telemetry']
    with SessionLocal() as db:
        assert db.get(DeviceTelemetrySnapshot, did).fields['uptime_seconds']['value'] == 30


def test_snapshot_migration_keeps_device_inventory(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from airlink.db import engine
    from test_api import tower
    did = device(client, owner, tower(client, owner))
    path = Path(__file__).resolve().parents[1] / 'database/versions/c75ef4816092_device_telemetry_snapshot.py'
    spec = importlib.util.spec_from_file_location('snapshot_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
    with SessionLocal() as db:
        assert db.get(Device, did) is not None
        db.add(DeviceTelemetrySnapshot(device_id=did, fields={}))
        db.commit()


@pytest.mark.parametrize('client_count', [12, 0])
def test_snmp_partial_walks_and_failure_keep_pre_outage_inventory(client, owner, monkeypatch, client_count):
    from test_api import tower
    tid = tower(client, owner)
    profile = client.post('/api/snmp-profiles/discovery-public', headers=owner,
                         json={'version': '2c'}).json()['id']
    did = client.post('/api/devices', headers=owner, json={
        'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.11',
        'vendor': 'mikrotik', 'snmp_profile_id': profile}).json()['id']
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=False))
    snmp = AsyncMock(return_value={
        'snmp_up': True, 'uptime_seconds': 90060, 'wireless_ssids': ['Tower radio'],
        'wireless_clients': client_count,
        'interfaces': {'1': {'name': 'ether1', 'type': 6, 'status': 1, 'speed_mbps': 1000}}})
    monkeypatch.setattr(worker, 'collect', snmp)
    clock = now()
    monkeypatch.setattr(worker, 'now', lambda: clock)
    monkeypatch.setattr(api, 'now', lambda: clock)

    def poll():
        async def run():
            await worker.poll(did, asyncio.Semaphore(1))
        asyncio.run(run())
        return client.get('/api/devices', headers=owner).json()[0]

    first = poll()
    keys = ('wireless_ssids', 'wireless_clients', 'ethernet_links')
    for interfaces in ({}, {'2': {'name': 'ether2', 'type': 6, 'status': 1, 'speed_mbps': 100}}):
        # Uptime can succeed while later OID walks time out or return partial data.
        snmp.return_value = {'snmp_up': True, 'uptime_seconds': 90120,
                             'wireless_ssids': [], 'interfaces': interfaces}
        clock += timedelta(minutes=1)
        partial = poll()
        for key in keys:
            assert partial['telemetry'][key] == first['telemetry'][key]
            assert partial['telemetry_field_times'][key] == first['telemetry_field_times'][key]
            assert key in partial['telemetry_stale_fields']

    # Empty defaults from a failed reading must not overwrite even a saved zero count.
    snmp.return_value = {'snmp_up': False, 'wireless_ssids': [],
                         'wireless_clients': 0, 'interfaces': {}, 'uptime_seconds': 0}
    for _ in range(3):
        clock += timedelta(minutes=1)
        down = poll()
    assert down['status'] == 'offline' and down['downtime_seconds'] == 120
    assert down['telemetry']['uptime_seconds'] == 90120
    for key in keys:
        assert down['telemetry'][key] == first['telemetry'][key]
        assert down['telemetry_field_times'][key] == first['telemetry_field_times'][key]
        assert key in down['telemetry_stale_fields']
    snmp.return_value = {'snmp_up': True, 'uptime_seconds': 30, 'wireless_ssids': ['New SSID'],
                         'wireless_clients': 0,
                         'interfaces': {'1': {'name': 'ether1', 'type': 6, 'status': 1, 'speed_mbps': 100}}}
    clock += timedelta(minutes=1)
    recovered = poll()
    assert recovered['status'] == 'online'
    assert recovered['telemetry']['wireless_ssids'] == ['New SSID']
    assert recovered['telemetry']['wireless_clients'] == 0
    assert recovered['telemetry']['ethernet_links'] == [{'name': 'ether1', 'speed_mbps': 100}]
    assert recovered['telemetry_stale_fields'] == []
