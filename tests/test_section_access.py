import pytest
from starlette.websockets import WebSocketDisconnect
from airlink import sas4
from airlink.db import SessionLocal
from airlink.models import UserSectionAccess
from airlink.section_access import OPERATIONAL, ASSIGNABLE, ALL
from test_api import user, tower, device


def grant(client, owner, manager_id, sections):
    result = client.put('/api/users/'+manager_id+'/sections', headers=owner, json={'sections':sections})
    assert result.status_code == 200, result.text
    assert result.json()['sections'] == [key for key in ASSIGNABLE if key in sections]


def test_owner_full_access_and_owner_only_permission_control(client, owner):
    mid, manager = user(client, owner, 'manager')
    vid, viewer = user(client, owner, 'viewer')
    own = client.get('/api/auth/me', headers=owner).json()
    assert own['sections'] == list(ALL)
    assert client.get('/api/auth/me', headers=manager).json()['sections'] == list(OPERATIONAL)
    for actor in (manager, viewer):
        assert client.put('/api/users/'+mid+'/sections', headers=actor, json={'sections':[]}).status_code == 403
    assert client.put('/api/users/'+own['id']+'/sections', headers=owner, json={'sections':[]}).status_code == 409
    assert client.put('/api/users/'+vid+'/sections', headers=owner, json={'sections':[]}).status_code == 422
    for key in ('managers','unknown'):
        assert client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections':[key]}).status_code == 422
    assert client.get('/api/auth/me', headers=owner).json()['sections'] == list(ALL)


@pytest.mark.parametrize('path', ['/api/dashboard','/api/towers','/api/places','/api/devices','/api/sectors',
    '/api/links','/api/alerts','/api/reports/availability.csv','/api/integrations/sas4/clients',
    '/api/integrations/sas4/online-count','/api/payments/gateways','/api/network','/api/updates','/api/users'])
def test_hidden_sections_block_direct_api_requests(client, owner, path):
    mid, manager = user(client, owner, 'manager')
    grant(client, owner, mid, [])
    assert client.get(path, headers=manager).status_code == 403
    assert client.get('/api/auth/me', headers=manager).json()['sections'] == []


def test_grants_revocation_scope_and_shared_read_access(client, owner):
    mid, manager = user(client, owner, 'manager')
    own_tower = tower(client, owner, manager=mid)
    other_tower = tower(client, owner, 'Other')
    did = device(client, owner, own_tower)
    device(client, owner, other_tower, ip='192.0.2.2')
    grant(client, owner, mid, ['towers'])
    assert [row['id'] for row in client.get('/api/towers', headers=manager).json()] == [own_tower]
    assert client.get('/api/devices/'+did+'/metrics', headers=manager).status_code == 403
    grant(client, owner, mid, ['network_map'])
    # Map receives scoped inventory but does not grant inventory writes or history.
    assert [row['id'] for row in client.get('/api/devices', headers=manager).json()] == [did]
    assert client.put('/api/towers/'+own_tower, headers=manager, json={'name':'Blocked','manager_id':mid}).status_code == 403
    assert client.delete('/api/devices/'+did, headers=manager).status_code == 403
    grant(client, owner, mid, ['monitoring'])
    assert client.get('/api/devices/'+did+'/metrics', headers=manager).status_code == 200
    grant(client, owner, mid, [])
    # Existing token is checked against current permissions; no re-login needed.
    assert client.get('/api/devices/'+did+'/metrics', headers=manager).status_code == 403
    assert client.get('/api/towers', headers=owner).status_code == 200
    assert client.delete('/api/users/'+mid, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(UserSectionAccess, mid) is None


def test_noc_only_exposes_online_count_not_isp_data(client, owner, monkeypatch):
    mid, manager = user(client, owner, 'manager')
    grant(client, owner, mid, ['noc'])
    assert client.put('/api/integrations/sas4', headers=manager,
        json={'username':'monitor','password':'private-password'}).status_code == 200
    monkeypatch.setattr(sas4, 'fetch_dashboard', lambda *args: {'online_users':7, 'balance':10000, 'total_users':500})
    result = client.get('/api/integrations/sas4/online-count', headers=manager)
    assert result.status_code == 200 and result.json() == {'online_users':7}
    for path in ('/api/integrations/sas4/dashboard','/api/integrations/sas4/clients','/api/integrations/sas4/device-access'):
        assert client.get(path, headers=manager).status_code == 403


def test_hidden_dashboard_cannot_be_read_through_websocket(client, owner):
    mid, manager = user(client, owner, 'manager')
    grant(client, owner, mid, ['isp_card'])
    with client.websocket_connect('/api/ws') as connection:
        connection.send_json({'token':manager['Authorization'].split()[1]})
        with pytest.raises(WebSocketDisconnect):
            connection.receive_json()


@pytest.mark.parametrize('section', ['software_updates', 'settings'])
def test_delegated_settings_and_updates_are_opt_in_and_revocable(client, owner, monkeypatch, section):
    from airlink import api
    mid, manager = user(client, owner, 'manager')
    calls = []
    def broker(action, payload=None):
        calls.append(action)
        return {'version':'test', 'status':'ok'}
    monkeypatch.setattr(api, 'broker', broker)
    assert client.get('/api/updates', headers=manager).status_code == 403
    assert client.get('/api/network', headers=manager).status_code == 403
    grant(client, owner, mid, [section])
    if section == 'software_updates':
        assert client.get('/api/updates', headers=manager).status_code == 200
        for action in ('check','download','verify','install','schedule'):
            assert client.post('/api/updates/'+action, headers=manager, json={}).status_code == 200
        assert client.post('/api/system/restart', headers=manager, json={}).status_code == 422
        assert client.post('/api/system/restart', headers=manager, json={'confirm':True}).status_code == 202
        assert client.get('/api/network', headers=manager).status_code == 403
        assert client.get('/api/audit', headers=manager).status_code == 403
    else:
        assert client.get('/api/network', headers=manager).status_code == 200
        assert client.post('/api/network/test', headers=manager, json={}).status_code == 200
        assert client.get('/api/system', headers=manager).status_code == 200
        assert client.get('/api/audit', headers=manager).status_code == 200
        saved = client.post('/api/snmp-profiles', headers=manager, json={'name':'Delegated','version':'2c','community':'private-value'})
        assert saved.status_code == 201
        profiles = client.get('/api/snmp-profiles', headers=manager)
        assert profiles.status_code == 200 and 'private-value' not in profiles.text
        assert client.get('/api/payments/gateways', headers=manager).status_code == 200
        assert client.get('/api/integrations/sas4/clients', headers=manager).status_code == 403
        assert client.post('/api/system/restart', headers=manager, json={'confirm':True}).status_code == 403
        assert client.get('/api/updates', headers=manager).status_code == 403
    assert client.get('/api/users', headers=manager).status_code == 403
    assert client.put('/api/users/'+mid+'/sections', headers=manager, json={'sections':list(ASSIGNABLE)}).status_code == 403
    grant(client, owner, mid, [])
    calls.clear()
    for path in ('/api/network/test','/api/updates/install','/api/system/restart'):
        assert client.post(path, headers=manager, json={'confirm':True}).status_code == 403
    assert not calls


def readonly_grant(client, owner, mid, sections, editable=()):
    response = client.put('/api/users/'+mid+'/sections', headers=owner,
                          json={'sections': sections, 'editable_sections': list(editable)})
    assert response.status_code == 200, response.text
    assert response.json()['editable_sections'] == [key for key in ASSIGNABLE if key in editable]


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/towers'), ('PUT', '/api/towers/any'), ('POST', '/api/towers/any/discover'),
    ('POST', '/api/places'), ('POST', '/api/devices'), ('PUT', '/api/devices/any'),
    ('DELETE', '/api/devices/any'), ('POST', '/api/sectors'), ('POST', '/api/alerts/any/acknowledge'),
    ('PUT', '/api/integrations/sas4'), ('PUT', '/api/integrations/sas4/device-access'),
    ('PUT', '/api/integrations/sas4/users/1'), ('POST', '/api/integrations/sas4/users/1/recharge'),
    ('PUT', '/api/payments/gateways/fib'), ('POST', '/api/payments/users/1'),
    ('POST', '/api/network/save'), ('POST', '/api/network/apply'), ('POST', '/api/snmp-profiles'),
    ('POST', '/api/updates/check'), ('POST', '/api/updates/install'), ('POST', '/api/updates/schedule'),
    ('POST', '/api/system/restart'),
])
def test_readonly_manager_cannot_write_through_direct_requests(client, owner, method, path):
    mid, manager = user(client, owner, 'manager')
    readonly_grant(client, owner, mid, list(ASSIGNABLE))
    response = client.request(method, path, headers=manager, json={})
    assert response.status_code == 403, response.text
    assert 'Read-only' in response.json()['detail']


def test_view_and_edit_grants_are_independent_and_immediate(client, owner, monkeypatch):
    from airlink import api
    from airlink.models import UserSectionEdits
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    calls = []
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: calls.append(action) or {})
    readonly_grant(client, owner, mid, ['towers', 'software_updates', 'settings'], ['towers'])
    assert client.put('/api/towers/'+tid, headers=manager, json={'name':'Allowed'}).status_code == 200
    assert client.get('/api/towers', headers=manager).status_code == 200
    assert client.get('/api/updates', headers=manager).status_code == 200
    assert client.get('/api/network', headers=manager).status_code == 200
    calls.clear()
    assert client.post('/api/updates/install', headers=manager, json={}).status_code == 403
    assert not calls
    readonly_grant(client, owner, mid, ['towers', 'software_updates'], ['software_updates'])
    assert client.put('/api/towers/'+tid, headers=manager, json={'name':'Blocked'}).status_code == 403
    assert client.post('/api/updates/check', headers=manager, json={}).status_code == 200
    assert client.get('/api/network', headers=manager).status_code == 403
    # Old clients cannot silently restore an explicit read-only policy.
    grant(client, owner, mid, ['towers', 'software_updates'])
    assert client.get('/api/auth/me', headers=manager).json()['editable_sections'] == ['software_updates']
    assert client.put('/api/users/'+mid+'/sections', headers=owner,
        json={'sections':['towers'], 'editable_sections':['settings']}).status_code == 422
    assert client.put('/api/users/'+mid+'/sections', headers=manager,
        json={'sections':['towers'], 'editable_sections':['towers']}).status_code == 403
    assert client.get('/api/auth/me', headers=owner).json()['editable_sections'] == list(ALL)
    assert client.put('/api/towers/'+tid, headers=owner, json={'name':'Owner'}).status_code == 200
    assert client.delete('/api/users/'+mid, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(UserSectionEdits, mid) is None
