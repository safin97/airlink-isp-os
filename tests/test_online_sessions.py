import threading
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from airlink import online_sessions as sessions, sas4, registration_usernames, customer_collector
from airlink.db import SessionLocal
from airlink.models import User, SAS4UserConnection
from test_api import user


class ImmediatePool:
    def submit(self, function, *args):
        task = Future()
        try:
            task.set_result(function(*args))
        except Exception as exc:
            task.set_exception(exc)
        return task

    def shutdown(self, **kwargs):
        pass


def setup(client, owner, monkeypatch):
    uid = client.get('/api/auth/me', headers=owner).json()['id']
    client.put('/api/integrations/sas4', headers=owner,
               json={'username': 'reader', 'password': 'secret'}).raise_for_status()
    service = sessions.OnlineSessions()
    service.pool = ImmediatePool()
    monkeypatch.setattr(sessions, 'service', service)
    monkeypatch.setattr(customer_collector, 'sessions', service)
    return uid, service


def response(rows, page=1, last_page=1, total=None):
    return {'clients': rows, 'page': page, 'last_page': last_page,
            'total': len(rows) if total is None else total}


def test_background_ready_before_opening_pages_and_new_login(client, owner, monkeypatch):
    uid, service = setup(client, owner, monkeypatch)
    rows = [{'username': f'customer-{n:02}', 'session_id': n, 'ip_address': f'10.0.0.{n+1}',
             'mac_address': f'AA:BB:CC:DD:EE:{n:02X}'} for n in range(10)]
    calls = []
    def fetch(connection, password, **kwargs):
        assert connection.username == 'reader' and password == 'secret'
        assert kwargs['count'] == 500 and kwargs['online'] is True
        calls.append(kwargs['page'])
        return response(rows)
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    collector = customer_collector.CustomerCollector()
    collector.poll_once()
    collector.poll_once()
    assert calls == [1]
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **k: pytest.fail('Page started an upstream fetch'))
    result = client.get('/api/integrations/sas4/online?page=2', headers=owner).json()
    assert result['total'] == 10 and len(result['clients']) == 3
    assert result['clients'][0]['username'] == 'customer-07'
    assert result['collection_status'] == 'available'
    assert 'matches' not in result and 'secret' not in str(result)
    filtered = client.get('/api/integrations/sas4/online?search=customer-08', headers=owner).json()
    assert filtered['total'] == 1 and filtered['clients'][0]['session_id'] == 8
    with SessionLocal() as db:
        # Registration matching reuses the complete list, including clients off the displayed page.
        matches, status = registration_usernames.UsernameLookup().lookup(db, db.get(User, uid))
        assert status == 'available' and matches['AA:BB:CC:DD:EE:00'] == 'customer-00'
    from conftest import PASSWORD
    login = client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).json()
    headers = {'Authorization': 'Bearer '+login['access_token']}
    assert client.get('/api/integrations/sas4/online', headers=headers).json()['total'] == 10


def test_complete_pagination_and_ambiguous_mac_matches(monkeypatch):
    mac = 'AA:BB:CC:DD:EE:01'
    def fetch(*args, page, **kwargs):
        return response([{'username': str(page), 'mac_address': mac}], page, 2, 2)
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    result = sessions.collect(SimpleNamespace(username='reader'), 'secret', threading.Event())
    assert len(result['clients']) == 2 and result['matches'] == {mac: None}
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **k: response([{'username': 'one'}], total=2))
    with pytest.raises(ValueError):
        sessions.collect(SimpleNamespace(username='reader'), 'secret', threading.Event())


def test_failed_refresh_keeps_explicitly_stale_sessions_then_expires(client, owner, monkeypatch):
    uid, service = setup(client, owner, monkeypatch)
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **k: response([{'username': 'old', 'mac_address': 'AA:BB:CC:DD:EE:01'}]))
    service.refresh_accounts(); service.refresh_accounts()
    service.retry_at.clear()
    calls = []
    def fail(*a, **k):
        calls.append(True)
        raise sas4.SAS4Error('private-upstream-error')
    monkeypatch.setattr(sas4, 'fetch_clients', fail)
    service.refresh_accounts(); service.refresh_accounts(); service.refresh_accounts()
    assert calls == [True]
    result = client.get('/api/integrations/sas4/online', headers=owner).json()
    assert result['collection_status'] == 'stale' and result['clients'][0]['username'] == 'old'
    assert 'private-upstream-error' not in str(result)
    with SessionLocal() as db:
        assert registration_usernames.UsernameLookup().lookup(db, db.get(User, uid)) == ({}, 'unavailable')
    next(iter(service.entries.values()))['collected'] -= sessions.MAX_AGE + 1
    result = client.get('/api/integrations/sas4/online', headers=owner).json()
    assert result['collection_status'] == 'unavailable' and result['clients'] == [] and result['total'] is None


def test_scope_credentials_permissions_and_inflight_revocation(client, owner, monkeypatch):
    uid, service = setup(client, owner, monkeypatch)
    mid, manager = user(client, owner, 'manager')
    client.put('/api/integrations/sas4', headers=manager,
               json={'username': 'other', 'password': 'other-secret'}).raise_for_status()
    monkeypatch.setattr(sas4, 'fetch_clients', lambda connection, *a, **k: response([{'username': connection.username}]))
    service.refresh_accounts(); service.refresh_accounts()
    assert client.get('/api/integrations/sas4/online', headers=manager).json()['clients'][0]['username'] == 'other'
    assert client.get('/api/integrations/sas4/online', headers=owner).json()['clients'][0]['username'] == 'reader'
    client.put('/api/integrations/sas4', headers=owner, json={'username': 'changed', 'password': 'new'}).raise_for_status()
    assert client.get('/api/integrations/sas4/online', headers=owner).json()['collection_status'] == 'warming'
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections': []}).raise_for_status()
    assert client.get('/api/integrations/sas4/online', headers=manager).status_code == 403
    with SessionLocal() as db:
        with pytest.raises(HTTPException):
            service.snapshot(db, db.get(User, mid))
    # Complete a fetch for the old credentials after configuration changes: it must not be published.
    old_key = next(key for key in service.entries if key[0] == uid)
    finished = Future()
    finished.set_result(next(iter(service.entries.values())))
    service.tasks[old_key] = finished
    service.refresh_accounts()
    assert old_key not in service.entries
    assert all(key[0] != mid for key in service.entries)


def test_cold_page_is_nonblocking_and_does_not_claim_zero_users(client, owner, monkeypatch):
    _, service = setup(client, owner, monkeypatch)
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **k: pytest.fail('Page started a fetch'))
    result = client.get('/api/integrations/sas4/online', headers=owner).json()
    assert result['collection_status'] == 'warming' and result['total'] is None
    assert service.tasks == {}


def test_bounded_queue_deduplication_and_account_rotation(client, owner, monkeypatch):
    _, service = setup(client, owner, monkeypatch)
    for n in range(3):
        _, manager = user(client, owner, 'manager', f'manager-{n}')
        client.put('/api/integrations/sas4', headers=manager,
                   json={'username': f'manager-{n}', 'password': 'secret'}).raise_for_status()
    waiting = []
    class Pool(ImmediatePool):
        def submit(self, function, *args):
            task = Future()
            waiting.append((task, args[0].username))
            return task
    service.pool = Pool()
    service.refresh_accounts(); service.refresh_accounts()
    assert len(waiting) == 2 and len(service.tasks) == 2
    for task, _ in waiting:
        task.set_result({'clients': [], 'matches': {}, 'fetched_at': 'now', 'collected': sessions.time.monotonic()})
    service.refresh_accounts()
    assert len(waiting) == 4 and len({name for _, name in waiting}) == 4
    assert len(service.tasks) == 2
    service.stop()
    assert not service.running and not service.entries and not service.tasks
