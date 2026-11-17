import json
import threading
from fastapi import HTTPException
from airlink import deye, deye_monitor, live_updates
from airlink.db import SessionLocal
from airlink.models import DeyeConnection, DeyeGridHistory, User, UserSectionAccess, UserSectionEdits
from test_api import user
from test_deye import CONFIG, PATH, cloud


def uid():
    with SessionLocal() as db:
        return db.query(DeyeConnection).one().user_id


def snapshot(headers):
    return live_updates.snapshot(headers['Authorization'].removeprefix('Bearer '))


def expire():
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        row.cache = {**row.cache, 'readings': {key: {**value, 'at': 0}
                     for key, value in deye.reading_cache(row).items()}}
        db.commit()


def test_monitor_reads_without_browser_and_pushes_private_cached_telemetry(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    before = snapshot(owner)
    assert before['deye']['readings'] == {}
    delay = deye_monitor.poll_account(uid())
    assert 0 < delay <= 5
    calls = len(cloud)
    frame = snapshot(owner)
    assert len(cloud) == calls  # WebSocket snapshots never call the cloud.
    assert frame['deye']['dashboard_station']['id'] == '123'
    assert frame['deye']['readings']['123']['solar_w'] == 4200
    assert 'deye' in live_updates.changes(before, frame)
    assert all(secret not in json.dumps(frame['deye']) for secret in (
        CONFIG['password'], CONFIG['app_secret'], CONFIG['account'], 'encrypted_token', '-token'))
    with SessionLocal() as db:
        assert db.query(DeyeGridHistory).count() == 1
    deye_monitor.poll_account(uid())
    assert len(cloud) == calls  # HTTP and background jobs share the cache.
    _, manager = user(client, owner, 'manager', 'no-solar')
    assert snapshot(manager)['deye'] is None
    client.delete(PATH, headers=owner)
    assert snapshot(owner)['deye'] == {'configured': False}


def test_monitor_follows_pinned_station_and_keeps_other_station_cached(client, owner, cloud, monkeypatch):
    original = deye.request
    def request(region, path, body, **kwargs):
        if path == '/station/list' and body['page'] == 2:
            return {'stationList': [{'id': 456, 'name': 'Second station'}], 'total': 51}
        return original(region, path, body, **kwargs)
    monkeypatch.setattr(deye, 'request', request)
    client.put(PATH, headers=owner, json=CONFIG)
    assert client.put(PATH + '/dashboard-station', headers=owner,
                      json={'station_id': '456', 'page': 2}).status_code == 200
    deye_monitor.poll_account(uid())
    assert [call[2]['stationId'] for call in cloud if call[1] == '/station/latest'] == [456]
    client.get(PATH + '/stations/123/latest', headers=owner)
    calls = len(cloud)
    deye_monitor.poll_account(uid())
    assert len(cloud) == calls
    frame = snapshot(owner)['deye']
    assert frame['dashboard_station']['id'] == '456'
    assert set(frame['readings']) == {'123', '456'}
    client.put(PATH + '/dashboard-station', headers=owner, json={'station_id': None})
    deye_monitor.poll_account(uid())
    assert snapshot(owner)['deye']['dashboard_station']['id'] == '123'


def test_monitor_shared_readings_revoke_immediately_and_inactive_owners_stop(client, owner, cloud):
    mid, manager = user(client, owner, 'manager', 'solar-monitor')
    client.put(PATH, headers=owner, json=CONFIG)
    owner_id = uid()
    client.put(PATH + '/sharing/' + mid, headers=owner, json={'enabled': True})
    deye_monitor.poll_account(owner_id)
    assert snapshot(manager)['deye']['readings']['123']['solar_w'] == 4200
    shared, owned = snapshot(manager)['deye'], snapshot(owner)['deye']
    assert shared['dashboard_station'] == owned['dashboard_station']
    for key in ('solar_w', 'load_w', 'battery_soc', 'fetched_at'):
        assert shared['readings']['123'][key] == owned['readings']['123'][key]
    calls = len(cloud)
    deye_monitor.poll_account(mid)
    assert len(cloud) == calls
    client.put(PATH + '/sharing/' + mid, headers=owner, json={'enabled': False})
    assert snapshot(manager)['deye'] is None
    client.put(PATH + '/sharing/' + mid, headers=owner, json={'enabled': True})
    with SessionLocal() as db:
        db.get(User, owner_id).active = False
        db.commit()
    deye_monitor.poll_account(owner_id)
    assert len(cloud) == calls
    assert snapshot(manager)['deye'] is None
    with SessionLocal() as db:
        db.get(User, owner_id).active = True
        db.delete(db.get(DeyeConnection, owner_id))
        db.commit()
    deye_monitor.poll_account(owner_id)
    assert len(cloud) == calls
    assert snapshot(manager)['deye'] == {'configured': False}


def test_monitor_failure_is_redacted_rate_limited_and_recovers(client, owner, cloud, monkeypatch):
    original = deye.request
    client.put(PATH, headers=owner, json=CONFIG)
    deye_monitor.poll_account(uid())
    expire()
    failures = []
    def fail(*args, **kwargs):
        failures.append(1)
        raise HTTPException(502, 'private-vendor-secret')
    monkeypatch.setattr(deye, 'request', fail)
    deye_monitor.poll_account(uid())
    frame = snapshot(owner)['deye']
    assert frame['monitor_error'] and frame['readings']['123']['error']
    assert 'solar_w' not in frame['readings']['123']
    assert 'private-vendor-secret' not in json.dumps(frame)
    assert client.get(PATH + '/stations/123/latest', headers=owner).status_code == 502
    deye_monitor.poll_account(uid())
    assert len(failures) == 1
    # Failure backoff remains 30 seconds despite the faster successful-reading cadence.
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        row.cache = {**row.cache, 'readings': {'123': {
            **row.cache['readings']['123'], 'at': deye.time.time() - 6}}}
        db.commit()
    assert deye_monitor.poll_account(uid()) == deye.ERROR_CACHE_SECONDS
    assert len(failures) == 1
    expire()
    monkeypatch.setattr(deye, 'request', original)
    deye_monitor.poll_account(uid())
    frame = snapshot(owner)['deye']
    assert frame['monitor_error'] is None
    assert frame['readings']['123']['solar_w'] == 4200
    expire()
    frame = snapshot(owner)['deye']
    assert frame['readings']['123']['error'] == 'Waiting for a new cloud reading.'


def test_cache_bound_preserves_dashboard_station(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    client.put(PATH + '/dashboard-station', headers=owner, json={'station_id': '123'})
    deye_monitor.poll_account(uid())
    for sid in range(200, 210):
        assert client.get(PATH + f'/stations/{sid}/latest', headers=owner).status_code == 200
    readings = snapshot(owner)['deye']['readings']
    assert len(readings) == 8 and '123' in readings and '209' in readings


def test_monitor_lifecycle_is_idempotent_and_slow_accounts_do_not_block_others(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    owner_id = uid()
    mid, manager = user(client, owner, 'owner', 'other-solar')
    with SessionLocal() as db:
        db.add(UserSectionAccess(user_id=mid, sections=['deye']))
        db.add(UserSectionEdits(user_id=mid, sections=['deye']))
        db.commit()
    client.put(PATH, headers=manager, json=CONFIG)
    started, release, other = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def poll(user_id):
        calls.append(user_id)
        if user_id == owner_id:
            started.set()
            release.wait(5)
        else:
            other.set()
    monkeypatch.setattr(deye_monitor, 'poll_account', poll)
    monitor = deye_monitor.DeyeMonitor()
    try:
        monitor.start()
        thread = monitor.thread
        monitor.start()
        assert monitor.thread is thread
        assert started.wait(3)
        assert other.wait(3)
        assert calls.count(owner_id) == 1 and calls.count(mid) == 1
    finally:
        release.set()
        monitor.stop()
    assert not thread.is_alive()
