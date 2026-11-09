import threading
from types import SimpleNamespace
from airlink import customer_collector as collector, sas4, online_sessions
from airlink.customer_probes import ProbeService
from test_api import user
from test_online_sessions import ImmediatePool, response


def setup_collector(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json={'username': 'reader', 'password': 'test-password'}).raise_for_status()
    client.put('/api/integrations/sas4/device-access', headers=owner, json={'api_username':'device-reader','api_password':'device-password'}).raise_for_status()
    probes = ProbeService()
    probes.pool = SimpleNamespace(submit=lambda *args: None)
    snapshots = online_sessions.OnlineSessions()
    snapshots.pool = ImmediatePool()
    monkeypatch.setattr(collector, 'probes', probes)
    monkeypatch.setattr(collector, 'sessions', snapshots)
    return collector.CustomerCollector(), probes, snapshots


def test_collects_all_readings_without_browser_requests(client, owner, monkeypatch):
    service, probes, snapshots = setup_collector(client, owner, monkeypatch)
    calls = []
    def fetch(connection, password, page, count, online):
        assert password == 'test-password' and count == 500 and online
        calls.append(page)
        return response([{'username': f'user-{n}', 'session_id': n,
                          'ip_address': f'192.168.1.{n}'} for n in range(1, 41)])
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    for _ in range(3):
        service.poll_once()
    assert calls == [1] and len(probes.pending) == 40
    # A full device queue must not stop SAS4 session and username refreshes.
    probes.pending.update(('busy', n) for n in range(64))
    snapshots.retry_at.clear()
    service.poll_once(); service.poll_once()
    assert calls == [1, 1]


def test_disabled_telemetry_still_collects_sessions_but_denied_accounts_are_skipped(client, owner, monkeypatch):
    service, probes, snapshots = setup_collector(client, owner, monkeypatch)
    client.put('/api/integrations/sas4/device-access', headers=owner, json={'enabled': False}).raise_for_status()
    manager_id, manager = user(client, owner, 'manager', 'collector-manager')
    client.put('/api/integrations/sas4', headers=manager, json={'username': 'manager-reader', 'password': 'test-password'}).raise_for_status()
    client.put('/api/users/'+manager_id+'/sections', headers=owner, json={'sections': ['towers']}).raise_for_status()
    calls = []
    def fetch(connection, *args, **kwargs):
        calls.append(connection.username)
        return response([{'username': 'user', 'ip_address': '192.168.1.1'}])
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    for _ in range(3):
        service.poll_once()
    assert calls == ['reader'] and probes.pending == set()
    assert len(snapshots.entries) == 1


def test_background_thread_starts_without_http_and_stops(monkeypatch):
    snapshots = online_sessions.OnlineSessions()
    monkeypatch.setattr(collector, 'sessions', snapshots)
    service = collector.CustomerCollector()
    called = threading.Event()
    monkeypatch.setattr(service, 'poll_once', called.set)
    service.start()
    try:
        assert called.wait(1) and snapshots.running
        thread = service.thread
        service.start()
        assert service.thread is thread
    finally:
        service.stop()
    assert not service.thread.is_alive() and not snapshots.running


def test_logged_out_server_collects_sessions_usernames_and_device_readings(client, owner, monkeypatch):
    import time
    from sqlalchemy import select
    from airlink import customer_probes, registration_usernames
    from airlink.db import SessionLocal
    from airlink.models import LoginSession, User
    from conftest import PASSWORD
    service, _, snapshots = setup_collector(client, owner, monkeypatch)
    snapshots.pool = None
    monkeypatch.setattr(online_sessions, 'service', snapshots)
    monkeypatch.setattr(collector, 'INTERVAL', .01)
    probes = ProbeService()
    monkeypatch.setattr(collector, 'probes', probes)
    monkeypatch.setattr(sas4, 'customer_probe_service', probes)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(True)
        return response([{'username': 'subscriber', 'session_id': 17, 'ip_address': '192.168.1.1',
                          'mac_address': 'AA:BB:CC:DD:EE:01'}])
    async def probe(*args):
        return {'telemetry_status': 'available', 'signal_dbm': -60, 'ssid': 'North',
                'ethernet_links': [{'name': 'ether1', 'speed_mbps': 1000}]}
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    monkeypatch.setattr(customer_probes, 'probe', probe)
    client.post('/api/auth/logout', headers=owner).raise_for_status()
    with SessionLocal() as db:
        assert not list(db.scalars(select(LoginSession).where(LoginSession.revoked.is_(False))))
    probes.start()
    service.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with probes.lock:
                if probes.cache:
                    break
            time.sleep(.01)
        with probes.lock:
            assert probes.cache
        assert calls == [True]
        with SessionLocal() as db:
            account = db.scalar(select(User).where(User.role == 'owner'))
            assert registration_usernames.UsernameLookup().lookup(db, account) == (
                {'AA:BB:CC:DD:EE:01': 'subscriber'}, 'available')
        login = client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).json()
        headers = {'Authorization': 'Bearer '+login['access_token']}
        result = client.get('/api/integrations/sas4/online', headers=headers).json()
        assert result['clients'][0]['signal_dbm'] == -60
        assert result['clients'][0]['ssid'] == 'North'
        assert result['clients'][0]['ethernet_links'][0]['speed_mbps'] == 1000
        assert calls == [True]
    finally:
        service.stop()
        probes.stop()
