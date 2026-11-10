import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from airlink import tower_routeros as panel, routeros_native
from airlink.device_management import ManagementError
from test_api import user, tower, device
from test_towers_device_login import BODY, PATH


def test_all_ports_mixed_radios_traffic_and_secrets_filtered():
    ports = [{'.id': '*%X' % n, 'name': 'ether%d' % n, 'disabled': 'false', 'running': 'true'} for n in range(1, 49)]
    ports[1]['running'] = 'false'
    ports[2]['disabled'] = 'true'
    async def read(path, payload=None):
        if path.startswith('interface?'): return ports + [{'name': 'wlan1', 'running': 'true'}, {'name': 'wifi1', 'running': 'false'}]
        if path.startswith('interface/ethernet?'): return ports
        if path == 'interface/monitor-traffic':
            assert payload == {'interface': 'all', 'once': ''}
            return [{'name': p['name'], 'rx-bits-per-second': str(i * 1e6), 'tx-bits-per-second': '0'} for i, p in enumerate(reversed(ports))]
        if path == 'interface/ethernet/monitor':
            assert len(payload['numbers'].split(',')) == 48
            return [{'name': p['name'], 'rate': '1Gbps', 'full-duplex': 'true'} for p in reversed(ports)]
        if path.startswith('interface/wireless?'): return [{'.id': '*A1', 'name': 'wlan1', 'ssid': 'Legacy', 'password': 'secret'}]
        if path.startswith('interface/wifi?') or path.startswith('interface/wifiwave2?'):
            return [{'.id': '*B1', 'name': 'wifi1', 'configuration.ssid': 'Modern'}]
        if '/registration-table?' in path:
            return [{'interface': 'wlan1', 'signal-strength': '-57', 'password': 'secret'}]
        if path.startswith('system/resource?'): return [{'version': '7', 'password': 'secret'}]
        return []
    data = asyncio.run(panel.snapshot(read))
    assert len(data['ethernet']) == 48
    assert data['ethernet'][0]['rx_bps'] == 47e6
    assert data['ethernet'][-1]['rx_bps'] == 0
    assert data['ethernet'][0]['speed_mbps'] == 1000
    assert data['ethernet'][1]['status'] == 'not running'
    assert data['ethernet'][2]['status'] == 'disabled'
    assert [r['ssid'] for r in data['wireless']] == ['Legacy', 'Modern']
    assert data['wireless'][0]['signal_dbm'] == -57
    assert len(data['registrations']) == 1
    assert 'secret' not in json.dumps(data)


def test_unknown_traffic_and_large_tables_are_not_truncated():
    async def read(path, payload=None):
        if path.startswith('interface?'): return [{'.id': '*1', 'name': 'ether1'}]
        if path.startswith('interface/ethernet?'): return [{'.id': '*1', 'name': 'ether1'}]
        return None
    data = asyncio.run(panel.snapshot(read))
    assert data['ethernet'][0]['rx_bps'] is None
    assert data['ethernet'][0]['status'] == 'unknown'
    assert data['warnings']
    with pytest.raises(ValueError): panel.items([{}] * 4097)


def change(**kw):
    return panel.Change(profile_id='p', **{'resource': 'identity', 'previous': {'name': 'Old'}, 'changes': {'name': 'New'}, **kw})


@pytest.mark.parametrize('kw', [
    {'changes': {'password': 'secret'}}, {'changes': {'name': 'bad\nname'}},
    {'resource': 'routes', 'action': 'add', 'changes': {'dst-address': 'bad', 'gateway': '1.1.1.1'}, 'previous': {}},
    {'resource': 'ethernet', 'record_id': '*1', 'changes': {'disabled': 'yes'}, 'previous': {'disabled': 'false'}},
    {'resource': 'ethernet', 'record_id': '*1', 'changes': {'mtu': '1'}, 'previous': {'mtu': '1500'}},
    {'resource': 'dns', 'changes': {'servers': 'not-an-ip'}, 'previous': {}},
    {'resource': 'identity', 'action': 'remove'},
    {'resource': 'wireless', 'record_id': '*1', 'previous': {'ssid': 'a'}, 'changes': {'ssid': 'é' * 17}},
    {'record_id': '../../other'}, {'previous': {}},
])
def test_invalid_changes(kw):
    with pytest.raises(ValidationError): change(**kw)


def test_conflict_and_controller_settings_never_write():
    write = AsyncMock()
    with pytest.raises(ManagementError, match='changed'):
        asyncio.run(panel.apply(AsyncMock(return_value=[{'name': 'Other'}]), write, change()))
    for guard in ({'dynamic': 'true'}, {'configuration.manager': 'capsman'}, {'ssid': None}):
        row = {'.id': '*1', 'ssid': 'Old', **guard}
        if guard == {'ssid': None}: del row['ssid']
        request = change(resource='wireless', record_id='*1', previous={'ssid': 'Old'}, changes={'ssid': 'New'})
        with pytest.raises(ManagementError):
            asyncio.run(panel.apply(AsyncMock(return_value=[row]), write, request))
    write.assert_not_called()


@pytest.mark.parametrize('resource,record,previous,changes', [
    ('identity', '', {'name': 'Old'}, {'name': 'New'}),
    ('ethernet', '*1', {'name': 'ether1', 'disabled': 'false'}, {'disabled': 'true'}),
    ('wireless', '*1', {'ssid': 'Old'}, {'ssid': 'New'}),
    ('wifi', '*1', {'configuration.ssid': 'Old'}, {'configuration.ssid': 'New'}),
    ('dns', '', {'servers': ''}, {'servers': '1.1.1.1,8.8.8.8'}),
    ('addresses', '*1', {'address': '192.0.2.1/24'}, {'address': '192.0.2.2/24'}),
    ('routes', '*1', {'distance': '1'}, {'distance': '2'}),
])
def test_native_writes_exactly_selected_fields(monkeypatch, resource, record, previous, changes):
    commands = []
    class Connection:
        def __init__(self, address, config): assert address == '192.0.2.1'
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def read(self, path, payload=None): return [{'.id': record, **previous}]
        async def command(self, path, values): commands.append((path, values))
    monkeypatch.setattr(routeros_native, 'Connection', Connection)
    request = change(resource=resource, record_id=record, previous=previous, changes=changes)
    result = asyncio.run(panel.change_once('192.0.2.1', {'transport': 'routeros'}, request))
    assert result['status'] == 'accepted'
    assert commands == [('/' + panel.DEFINITIONS[resource][1] + '/set', {**changes, **({'.id': record} if record else {})})]


@pytest.mark.parametrize('action', ['add', 'remove'])
def test_address_add_delete_and_missing_interface(action):
    row = {'.id': '*1', 'address': '192.0.2.1/24', 'interface': 'ether1', 'disabled': 'false'}
    async def read(path, payload=None): return [{'name': 'ether1'}] if path.startswith('interface?') else [row]
    write = AsyncMock()
    request = change(resource='addresses', action=action, record_id='' if action == 'add' else '*1',
        previous={} if action == 'add' else {k: v for k, v in row.items() if k != '.id'},
        changes={'address': '192.0.2.2/24', 'interface': 'ether1'} if action == 'add' else {})
    assert asyncio.run(panel.apply(read, write, request))['status'] == 'accepted'
    assert write.call_args.args[0] == 'ip/address/' + action
    if action == 'add':
        request.changes['interface'] = 'gone'
        with pytest.raises(ManagementError, match='interface'):
            asyncio.run(panel.apply(read, write, request))
        assert write.call_count == 1


def test_rest_write_timeout_is_not_retried_on_http():
    requests = []
    def handler(req):
        requests.append(req)
        if req.method == 'GET': return httpx.Response(200, json=[{'name': 'Old'}])
        assert req.method == 'POST' and req.url.path == '/rest/system/identity/set'
        assert json.loads(req.content) == {'name': 'New'}
        raise httpx.ReadTimeout('private response')
    with pytest.raises(ManagementError, match='unknown'):
        asyncio.run(panel.change_once('192.0.2.1', {'api_username': 'admin', 'api_password': 'secret', 'protocol': 'both'}, change(), httpx.MockTransport(handler)))
    assert sum(r.method == 'POST' for r in requests) == 1
    assert all(r.url.scheme == 'https' for r in requests)


def test_settings_route_requires_edit_scope_grant_lock_and_sanitizes_errors(client, owner, monkeypatch):
    from airlink import api
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    did = device(client, owner, tid)
    client.put('/api/devices/' + did, headers=owner, json={'tower_id': tid, 'name': 'Router', 'vendor': 'mikrotik', 'ip_address': '192.0.2.1'}).raise_for_status()
    pid = client.post(PATH, headers=owner, json={**BODY, 'manager_ids': [mid], 'transport': 'routeros'}).json()['id']
    endpoint = '/api/devices/' + did + '/settings'
    body = {**change().model_dump(), 'profile_id': pid}
    save = AsyncMock(return_value={'status': 'accepted'})
    monkeypatch.setattr(panel, 'save', save)
    client.put('/api/users/' + mid + '/sections', headers=owner, json={'sections': ['towers'], 'editable_sections': [], 'deletable_sections': []}).raise_for_status()
    assert client.put(endpoint, headers=manager, json=body).status_code == 403
    save.assert_not_called()
    client.put('/api/users/' + mid + '/sections', headers=owner, json={'sections': ['towers'], 'editable_sections': ['towers'], 'deletable_sections': []}).raise_for_status()
    result = client.put(endpoint, headers=manager, json=body)
    assert result.status_code == 200, result.text
    assert save.call_args.args[0] == '192.0.2.1'
    assert save.call_args.args[1]['api_password'] == BODY['password']
    outside = device(client, owner, tower(client, owner, 'Other'), '192.0.2.2')
    assert client.put('/api/devices/' + outside + '/settings', headers=manager, json=body).status_code == 404
    assert client.put(endpoint, headers=manager, json={**body, 'ip_address': '192.0.2.99'}).status_code == 422
    lock = api.cache.lock('online-device-change:192.0.2.1', timeout=60)
    lock.acquire()
    assert client.put(endpoint, headers=manager, json=body).status_code == 409
    lock.release()
    save.side_effect = RuntimeError('private-device-secret')
    failure = client.put(endpoint, headers=manager, json=body)
    assert failure.status_code == 502 and 'private-device-secret' not in failure.text
    client.put(PATH + '/' + pid, headers=owner, json={**BODY, 'manager_ids': []}).raise_for_status()
    assert client.put(endpoint, headers=manager, json=body).status_code == 404
    assert save.call_count == 2


def test_mikrotik_login_dispatches_enhanced_panel_without_first_16_limit(client, owner, monkeypatch):
    tid = tower(client, owner)
    did = device(client, owner, tid)
    client.put('/api/devices/' + did, headers=owner, json={'tower_id': tid, 'name': 'Switch', 'vendor': 'mikrotik_switch', 'ip_address': '192.0.2.1'}).raise_for_status()
    pid = client.post(PATH, headers=owner, json={**BODY, 'transport': 'routeros'}).json()['id']
    class Connection:
        def __init__(self, address, config): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def read(self, path, payload=None):
            if path.startswith(('interface?', 'interface/ethernet?')):
                return [{'.id': '*%X' % n, 'name': 'ether%d' % n, 'disabled': 'false', 'running': 'true'} for n in range(1, 49)]
            return []
    monkeypatch.setattr(routeros_native, 'Connection', Connection)
    result = client.post('/api/devices/' + did + '/login', headers=owner, json={'profile_id': pid})
    assert result.status_code == 200, result.text
    assert len(result.json()['ethernet']) == 48
    assert 'tower_settings' in result.json()
    assert BODY['password'] not in result.text
