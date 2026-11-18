from airlink import sas4, sas4_dashboard, customer_collector, online_sessions
from airlink.db import SessionLocal
from airlink.models import User
from test_api import user
from test_online_sessions import ImmediatePool


def setup(client, owner, monkeypatch):
    account_id = client.get('/api/auth/me', headers=owner).json()['id']
    client.put('/api/integrations/sas4', headers=owner, json={'username':'owner-sas4', 'password':'secret'}).raise_for_status()
    service = sas4_dashboard.DashboardSnapshots()
    service.pool = ImmediatePool()
    monkeypatch.setattr(sas4_dashboard, 'service', service)
    monkeypatch.setattr(customer_collector, 'dashboards', service)
    return account_id, service


def test_dashboard_collected_without_browser_and_reads_do_not_fetch(client, owner, monkeypatch):
    _, service = setup(client, owner, monkeypatch)
    calls = []
    monkeypatch.setattr(sas4, 'fetch_dashboard', lambda connection, password: calls.append(connection.username) or {'online_users':12, 'balance':'100'})
    collector = customer_collector.CustomerCollector()
    collector.poll_once(); collector.poll_once()
    assert calls == ['owner-sas4']
    for _ in range(3):
        result = client.get('/api/integrations/sas4/dashboard', headers=owner).json()
        assert result['online_users'] == 12 and result['collection_status'] == 'available'
    assert calls == ['owner-sas4']
    monkeypatch.setattr(sas4, 'fetch_dashboard', lambda *a: {'online_users':15})
    service.retry_at.clear()
    collector.poll_once(); collector.poll_once()
    assert client.get('/api/integrations/sas4/dashboard', headers=owner).json()['online_users'] == 15


def test_cold_and_failed_dashboard_do_not_invent_zero_counts(client, owner, monkeypatch):
    _, service = setup(client, owner, monkeypatch)
    result = client.get('/api/integrations/sas4/dashboard', headers=owner).json()
    assert result['collection_status'] == 'warming' and result['online_users'] is None
    assert not service.tasks
    monkeypatch.setattr(sas4, 'fetch_dashboard', lambda *a: {'online_users':5})
    service.refresh_accounts(); service.refresh_accounts()
    def fail(*a): raise RuntimeError('PRIVATE_UPSTREAM_ERROR')
    monkeypatch.setattr(sas4, 'fetch_dashboard', fail)
    service.retry_at.clear()
    service.refresh_accounts(); service.refresh_accounts()
    result = client.get('/api/integrations/sas4/dashboard', headers=owner).json()
    assert result['collection_status'] == 'stale' and result['online_users'] == 5
    assert 'PRIVATE' not in str(result)
    next(iter(service.entries.values()))['collected'] -= online_sessions.MAX_AGE + 1
    result = client.get('/api/integrations/sas4/dashboard', headers=owner).json()
    assert result['collection_status'] == 'unavailable' and result['online_users'] is None


def test_dashboard_isolated_by_account_credentials_and_permissions(client, owner, monkeypatch):
    oid, service = setup(client, owner, monkeypatch)
    mid, manager = user(client, owner, 'manager', 'dashboard-manager')
    client.put('/api/integrations/sas4', headers=manager, json={'username':'manager-sas4', 'password':'secret'}).raise_for_status()
    monkeypatch.setattr(sas4, 'fetch_dashboard', lambda connection, password: {'balance':connection.username, 'online_users':4})
    service.refresh_accounts(); service.refresh_accounts()
    assert client.get('/api/integrations/sas4/dashboard', headers=owner).json()['balance'] == 'owner-sas4'
    assert client.get('/api/integrations/sas4/dashboard', headers=manager).json()['balance'] == 'manager-sas4'
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections':['noc']}).raise_for_status()
    assert client.get('/api/integrations/sas4/dashboard', headers=manager).status_code == 403
    assert client.get('/api/integrations/sas4/online-count', headers=manager).json() == {'online_users':4}
    client.put('/api/integrations/sas4', headers=owner, json={'username':'new-owner', 'password':'new-secret'}).raise_for_status()
    assert client.get('/api/integrations/sas4/dashboard', headers=owner).json()['collection_status'] == 'warming'
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections':[]}).raise_for_status()
    service.refresh_accounts()
    assert all(key[0] != mid for key in service.entries)
