import json
from unittest.mock import AsyncMock

import pytest
from airlink import online_device
from airlink.db import SessionLocal
from airlink.models import DeviceLoginProfile
from airlink.security import cipher
from test_api import user, tower, device

PATH = '/api/towers-api-profiles'
BODY = {'name': 'Tower radios', 'username': 'reader', 'password': 'private-tower-api-password',
        'protocol': 'https', 'port': 8443, 'verify_tls': True}


def test_towers_profile_save_edit_and_no_password_readback(client, owner):
    result = client.post(PATH, headers=owner, json=BODY)
    assert result.status_code == 201, result.text
    pid = result.json()['id']
    assert BODY['password'] not in result.text
    with SessionLocal() as db:
        config = db.get(DeviceLoginProfile, pid).encrypted_config
        assert BODY['password'] not in config
        assert json.loads(cipher().decrypt(config.encode()))['api_password'] == BODY['password']
    edited = client.put(PATH+'/'+pid, headers=owner, json={**BODY, 'password': None, 'name': 'New name'})
    assert edited.status_code == 200 and edited.json()['has_password']
    assert BODY['password'] not in client.get(PATH, headers=owner).text
    # Existing reusable logins remain available from either sidebar page.
    assert client.get('/api/integrations/sas4/device-login-profiles', headers=owner).json()[0]['id'] == pid
    invalid = client.post(PATH, headers=owner, json={**BODY, 'port': 0})
    assert invalid.status_code == 422 and BODY['password'] not in invalid.text
    assert client.delete(PATH+'/'+pid, headers=owner).status_code == 204


@pytest.mark.parametrize('vendor', ['generic', 'mikrotik_switch'])
def test_tower_login_requires_both_device_scope_and_profile_grant(client, owner, monkeypatch, vendor):
    mid, manager = user(client, owner, 'manager')
    _, other = user(client, owner, 'manager', 'other')
    tid = tower(client, owner, manager=mid)
    did = device(client, owner, tid)
    edited = client.put('/api/devices/'+did, headers=owner, json={
        'tower_id': tid, 'name': 'Switch', 'ip_address': '192.0.2.1', 'vendor': vendor})
    assert edited.status_code == 200 and edited.json()['vendor'] == vendor
    saved = client.get('/api/devices', headers=owner).json()[0]
    assert saved['vendor_label'] == ('MikroTik switch' if vendor == 'mikrotik_switch' else 'Unknown / Generic')
    outside = device(client, owner, tower(client, owner, 'Other'), '192.0.2.2')
    pid = client.post(PATH, headers=owner, json={**BODY, 'manager_ids': [mid]}).json()['id']
    client.put('/api/users/'+mid+'/sections', headers=owner,
               json={'sections': ['towers'], 'editable_sections': [], 'deletable_sections': []}).raise_for_status()
    visible = client.get(PATH, headers=manager)
    assert visible.status_code == 403
    assert client.get(PATH, headers=other).status_code == 403
    assert client.post(PATH, headers=manager, json=BODY).status_code == 403
    assert client.put(PATH+'/'+pid, headers=manager, json=BODY).status_code == 403
    assert client.delete(PATH+'/'+pid, headers=manager).status_code == 403
    collect = AsyncMock(return_value={'vendor': 'MikroTik', 'ethernet': [], 'wireless': []})
    monkeypatch.setattr(online_device, 'collect', collect)
    response = client.post('/api/devices/'+did+'/login', headers=manager, json={'profile_id': pid})
    assert response.status_code == 200, response.text
    assert response.json()['credential_source'] == BODY['name']
    assert BODY['password'] not in response.text
    address, config = collect.call_args.args
    assert address == '192.0.2.1'
    assert config['vendor_hint'] == ('mikrotik' if vendor == 'mikrotik_switch' else 'generic')
    assert config['api_username'] == 'reader' and config['api_password'] == BODY['password']
    assert config['protocol'] == 'https' and config['port'] == 8443 and config['verify_tls'] is True
    assert collect.call_count == 1
    assert client.post('/api/devices/'+outside+'/login', headers=manager, json={'profile_id': pid}).status_code == 404
    assert client.post('/api/devices/'+did+'/login', headers=other, json={'profile_id': pid}).status_code == 404
    assert client.post('/api/devices/'+did+'/login', headers=manager,
                       json={'profile_id': pid, 'ip_address': '192.0.2.99'}).status_code == 422
    # Revoking the profile is enforced on refresh, not just in the selector.
    client.put(PATH+'/'+pid, headers=owner, json={**BODY, 'manager_ids': []}).raise_for_status()
    assert client.post('/api/devices/'+did+'/login', headers=manager, json={'profile_id': pid}).status_code == 404
    assert collect.call_count == 1
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections': ['isp_card']}).raise_for_status()
    assert client.get(PATH, headers=manager).status_code == 403
    assert client.post('/api/devices/'+did+'/login', headers=manager, json={'profile_id': pid}).status_code == 403


@pytest.mark.parametrize('failure,code', [(PermissionError('secret'), 502), (TimeoutError('secret'), 504), (RuntimeError('secret'), 502)])
def test_failed_or_disabled_login_is_safe(client, owner, monkeypatch, failure, code):
    did = device(client, owner, tower(client, owner))
    pid = client.post(PATH, headers=owner, json=BODY).json()['id']
    collect = AsyncMock(side_effect=failure)
    monkeypatch.setattr(online_device, 'collect', collect)
    result = client.post('/api/devices/'+did+'/login', headers=owner, json={'profile_id': pid})
    assert result.status_code == code and 'secret' not in result.text
    client.put(PATH+'/'+pid, headers=owner, json={**BODY, 'enabled': False}).raise_for_status()
    assert client.post('/api/devices/'+did+'/login', headers=owner, json={'profile_id': pid}).status_code == 409
    assert collect.call_count == 1
    _, viewer = user(client, owner, 'viewer')
    assert client.get(PATH, headers=viewer).status_code == 403
    assert client.post('/api/devices/'+did+'/login', headers=viewer, json={'profile_id': pid}).status_code == 403


@pytest.mark.parametrize('transport,port', [('routeros',None), ('routeros_tls',None), ('routeros',18728)])
def test_native_profile_routes_to_routeros_with_saved_credentials(client, owner, monkeypatch, transport, port):
    from airlink import routeros_native
    tid = tower(client, owner)
    did = device(client, owner, tid)
    profile = client.post(PATH, headers=owner, json={**BODY, 'transport': transport, 'port': port})
    assert profile.status_code == 201, profile.text
    assert profile.json()['transport'] == transport
    pid = profile.json()['id']
    observed = []
    class Connection:
        def __init__(self, address, config): observed.append((address, config))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def read(self, path, payload=None):
            if path.startswith('interface/ethernet?'):
                return [{'.id':'*1', 'name':'ether1', 'running':'true'}]
            if path == 'interface/ethernet/monitor':
                return [{'status':'link-ok', 'rate':'1Gbps'}]
            if path.startswith('system/identity'): return [{'name':'Roof Router'}]
            return []
    monkeypatch.setattr(routeros_native, 'Connection', Connection)
    result = client.post('/api/devices/'+did+'/login', headers=owner, json={'profile_id':pid})
    assert result.status_code == 200, result.text
    assert result.json()['ethernet'][0]['speed_mbps'] == 1000
    assert result.json()['connection']['transport'] == transport
    assert observed[0][0] == '192.0.2.1'
    assert observed[0][1]['port'] == port
    assert observed[0][1]['api_password'] == BODY['password']
    assert BODY['password'] not in result.text
    # Old clients omitting the new field cannot silently change a saved API transport.
    edited = client.put(PATH+'/'+pid, headers=owner, json={**BODY, 'password': None, 'port':port})
    assert edited.status_code == 200 and edited.json()['transport'] == transport


def test_login_profile_picker_is_device_scoped_and_grant_filtered(client, owner):
    mid, manager = user(client, owner, 'manager')
    did = device(client, owner, tower(client, owner, manager=mid))
    outside = device(client, owner, tower(client, owner, 'Outside'), '192.0.2.2')
    shared = client.post(PATH, headers=owner, json={**BODY,'manager_ids':[mid]}).json()['id']
    client.post(PATH, headers=owner, json={**BODY,'name':'Owner only'}).raise_for_status()
    path = '/api/devices/'+did+'/login-profiles'
    response = client.get(path, headers=manager)
    assert response.status_code == 200, response.text
    assert [p['id'] for p in response.json()] == [shared]
    assert BODY['password'] not in response.text
    assert client.get('/api/devices/'+outside+'/login-profiles', headers=manager).status_code == 404
    client.put(PATH+'/'+shared, headers=owner, json={**BODY,'manager_ids':[]}).raise_for_status()
    assert client.get(path, headers=manager).json() == []
    assert client.get(PATH, headers=manager).status_code == 403


@pytest.mark.parametrize('failure', ['native', 'eof'])
def test_native_failure_does_not_expose_device_response(client, owner, monkeypatch, failure):
    from airlink.routeros_native import APIError
    did = device(client, owner, tower(client, owner))
    pid = client.post(PATH, headers=owner, json={**BODY, 'transport':'routeros'}).json()['id']
    monkeypatch.setattr(online_device, 'collect', AsyncMock(side_effect=(APIError if failure == 'native' else EOFError)('private-device-message')))
    result = client.post('/api/devices/'+did+'/login', headers=owner, json={'profile_id':pid})
    assert result.status_code == 502 and 'private-device-message' not in result.text
