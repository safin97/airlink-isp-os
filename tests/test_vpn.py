import base64
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from airlink import api
from airlink.db import SessionLocal
from airlink.models import AuditLog
from network import vpn
from test_api import user

SETTINGS = {'server': 'vpn.example.com', 'username': 'vpn-user', 'password': 'vpn-pass-!,$',
            'psk': 'shared-key-!,=', 'routes': ['192.168.88.0/24']}


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_vpn_is_strictly_owner_only(client, owner, monkeypatch, role):
    uid, account = user(client, owner, role, 'vpn-' + role)
    if role == 'manager':
        response = client.put('/api/users/' + uid + '/sections', headers=owner,
                              json={'sections': ['settings'], 'editable_sections': ['settings']})
        assert response.status_code == 200
    calls = []
    monkeypatch.setattr(api, 'broker', lambda *args: calls.append(args) or {})
    assert client.get('/api/vpn').status_code == 401
    assert client.get('/api/vpn', headers=account).status_code == 403
    for action in ('save', 'connect', 'disconnect', 'delete'):
        assert client.post('/api/vpn/' + action, headers=account, json=SETTINGS if action == 'save' else {}).status_code == 403
    assert calls == []
    assert client.get('/api/vpn', headers=owner).status_code == 200
    assert client.post('/api/vpn/save', headers=owner, json=SETTINGS).status_code == 200
    assert client.post('/api/vpn/connect', headers=owner, json={}).status_code == 200
    count = len(calls)
    assert client.post('/api/vpn/shell', headers=owner, json={}).status_code == 404
    assert client.post('/api/vpn/connect', headers=owner, json={'uuid': 'other-profile'}).status_code == 422
    assert client.post('/api/vpn/save', headers=owner, json={**SETTINGS, 'command': 'bad'}).status_code == 422
    assert len(calls) == count
    with SessionLocal() as db:
        logs = [r.action + str(r.target) for r in db.scalars(select(AuditLog))]
    assert 'vpn.save' in logs[-2] and SETTINGS['password'] not in str(logs) and SETTINGS['psk'] not in str(logs)


@pytest.mark.parametrize('key,value', [
    ('server', 'https://vpn.example.com'), ('server', '127.0.0.1'), ('server', '300.1.2.3'),
    ('server', '::1'), ('server', 'bad\nserver'), ('username', ''), ('password', None),
    ('psk', 'x\x00secret'), ('routes', ['0.0.0.0/0']), ('routes', ['192.168.1.2/24']),
    ('routes', ['::/0']), ('routes', ['127.0.0.0/8']), ('routes', '192.168.0.0/24'),
])
def test_invalid_settings(key, value):
    with pytest.raises(ValueError):
        vpn.validate({**SETTINGS, key: value})


def test_blank_secrets_preserved_and_required():
    value = {**SETTINGS, 'password': '', 'psk': '', 'routes': ['192.168.88.0/24'] * 2}
    with pytest.raises(ValueError, match='password'):
        vpn.validate(value)
    assert vpn.validate(value, {'password': SETTINGS['password'], 'ipsec-psk': SETTINGS['psk']}) == SETTINGS
    assert vpn.validate({**SETTINGS, 'server': '203.0.113.7'})['server'] == '203.0.113.7'


class FakeManager:
    def __init__(self):
        self.path = None
        self.data = {}
        self.secret = {}
        self.state = 7
        self.writes = []
        self.closed = 0

    def profile(self): return self.path, self.data
    def secrets(self, path): return self.secret if path else {}
    def active(self): return ('/active/1', self.state, ['10.0.0.2']) if self.state != 7 else (None, 7, [])
    def close(self): self.closed += 1
    def save(self, path, value):
        self.writes.append(('save', value))
        self.path = '/profiles/1'
        self.data = {'vpn': {'data': {'gateway': value['server'], 'user': value['username']}},
                     'ipv4': {'route-data': [{'dest': r.split('/')[0], 'prefix': int(r.split('/')[1])} for r in value['routes']]}}
        self.secret = {'password': value['password'], 'ipsec-psk': value['psk']}
    def connect(self, path): self.writes.append(('connect', path)); self.state = 1
    def disconnect(self, path): self.writes.append(('disconnect', path)); self.state = 7
    def delete(self, path): self.writes.append(('delete', path)); self.path = None; self.data = {}; self.secret = {}


@pytest.fixture
def manager(monkeypatch):
    instance = FakeManager()
    monkeypatch.setattr(vpn, 'supported', lambda: True)
    monkeypatch.setattr(vpn, 'NetworkManager', lambda: instance)
    return instance


def test_save_connect_status_disconnect_and_remove(manager):
    assert vpn.action('status', {})['status'] == 'not_configured'
    with pytest.raises(ValueError, match='Save'):
        vpn.action('connect', {})
    result = vpn.action('save', SETTINGS)
    assert result['server'] == SETTINGS['server'] and result['has_psk'] and result['has_password']
    assert SETTINGS['password'] not in json.dumps(result) and SETTINGS['psk'] not in json.dumps(result)
    assert vpn.action('connect', {})['status'] == 'connecting'
    vpn.action('connect', {})
    assert len([w for w in manager.writes if w[0] == 'connect']) == 1
    manager.state = 5
    assert vpn.action('status', {})['status'] == 'connected'
    with pytest.raises(ValueError, match='Disconnect'):
        vpn.action('save', SETTINGS)
    with pytest.raises(ValueError, match='Disconnect'):
        vpn.action('delete', {})
    assert vpn.action('disconnect', {})['status'] == 'disconnected'
    assert vpn.action('save', {**SETTINGS, 'password': '', 'psk': ''})['has_password']
    assert manager.writes[-1][1]['psk'] == SETTINGS['psk']
    assert vpn.action('delete', {})['configured'] is False
    assert manager.secret == {} and manager.closed >= 10


def test_unsupported_and_raw_errors_never_escape(manager, monkeypatch):
    def fail(): raise RuntimeError('D-Bus error with ' + SETTINGS['psk'])
    manager.profile = fail
    with pytest.raises(ValueError) as error:
        vpn.action('status', {})
    assert SETTINGS['psk'] not in str(error.value)
    assert manager.closed == 1
    monkeypatch.setattr(vpn, 'supported', lambda: False)
    assert not vpn.action('status', {})['supported']
    with pytest.raises(ValueError, match='installed'):
        vpn.action('connect', {})
    with pytest.raises(ValueError, match='Unknown'):
        vpn.action('shell', {})
    with pytest.raises(ValueError, match='settings'):
        vpn.action('connect', {'uuid': 'other'})


def test_networkmanager_profile_secrets_routes_and_root_permissions():
    manager = object.__new__(vpn.NetworkManager)
    manager.dbus = SimpleNamespace(Dictionary=lambda value, **kw: value, Array=lambda value, **kw: value, UInt32=int)
    saved = []
    manager.interface = lambda *a: SimpleNamespace(AddConnection=lambda value, **kw: saved.append(value))
    manager.save(None, SETTINGS)
    value = saved[0]
    assert value['connection']['uuid'] == vpn.PROFILE_UUID
    assert value['connection']['permissions'] == ['user:root:']
    assert not value['connection']['autoconnect']
    assert value['vpn']['data']['ipsec-enabled'] == 'yes'
    assert SETTINGS['psk'] not in str(value['vpn']['data'])
    assert value['vpn']['secrets'] == {'password': SETTINGS['password'],
                                     'ipsec-psk': '0s' + base64.b64encode(SETTINGS['psk'].encode()).decode()}
    assert value['ipv4']['never-default'] and value['ipv4']['ignore-auto-dns'] and value['ipv4']['ignore-auto-routes']
    assert value['ipv4']['route-data'] == [{'dest': '192.168.88.0', 'prefix': 24}]
    assert value['ipv6']['method'] == 'disabled'


def test_psk_starting_with_plugin_encoding_prefix_remains_literal():
    manager = object.__new__(vpn.NetworkManager)
    encoded = '0s' + base64.b64encode(b'0s-literal-shared-key').decode()
    manager.interface = lambda *a: SimpleNamespace(GetSecrets=lambda *a, **kw: {'vpn': {'secrets': {'ipsec-psk': encoded}}})
    assert manager.secrets('/profile')['ipsec-psk'] == '0s-literal-shared-key'
