import asyncio
import json
import httpx
import pytest
from airlink import online_device, sas4, sas4_reports
from test_api import user

PATH = '/api/integrations/sas4/online-device'
QUERY = {'username': 'subscriber', 'ip_address': '10.2.3.4', 'session_id': '90'}


def setup_login(client, owner, monkeypatch):
    assert client.put('/api/integrations/sas4', headers=owner,
                      json={'username': 'radius-reader', 'password': 'sas-secret'}).status_code == 200
    monkeypatch.setattr(sas4_reports, 'fetch_managers', lambda *a, **kw: [{'id': 4, 'username': 'North'}])
    assert client.put('/api/device-api-access', headers=owner, json={
        'scope': 'isp_manager', 'target_id': '4', 'username': 'device-reader',
        'password': 'device-secret', 'protocol': 'both'}).status_code == 200
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **kw: {
        'clients': [{'username': 'subscriber', 'ip_address': '10.2.3.4', 'session_id': 90, 'manager': 'North'}],
        'last_page': 1})


def test_verified_session_uses_scoped_saved_login(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    calls = []
    async def collect(address, config):
        calls.append(address)
        assert config['api_username'] == 'device-reader'
        assert config['api_password'] == 'device-secret'
        assert config['protocol'] == 'both'
        return {'vendor': 'MikroTik', 'wireless': [], 'ethernet': [], 'pppoe': []}
    monkeypatch.setattr(online_device, 'collect', collect)
    result = client.get(PATH, headers=owner, params=QUERY)
    assert result.status_code == 200, result.text
    assert result.json()['credential_source'] == 'North'
    assert 'secret' not in result.text and 'device-reader' not in result.text
    for change in ({'ip_address': '10.2.3.5'}, {'session_id': '91'}, {'username': 'other'}):
        assert client.get(PATH, headers=owner, params={**QUERY, **change}).status_code == 409
    assert client.get(PATH, headers=owner, params={**QUERY, 'ip_address': '127.0.0.1'}).status_code == 422
    _, manager = user(client, owner, 'manager')
    assert client.get(PATH, headers=manager, params=QUERY).status_code == 409
    assert client.get(PATH, params=QUERY).status_code == 401
    assert calls == ['10.2.3.4']


def test_disabled_or_different_manager_never_connects(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    async def forbidden(*args):
        pytest.fail('Must not connect without this manager’s enabled credentials')
    monkeypatch.setattr(online_device, 'collect', forbidden)
    monkeypatch.setattr(sas4_reports, 'fetch_managers', lambda *a, **kw: [{'id': 5, 'username': 'North'}])
    assert client.get(PATH, headers=owner, params=QUERY).status_code == 409
    monkeypatch.setattr(sas4_reports, 'fetch_managers', lambda *a, **kw: [{'id': 4, 'username': 'North'}])
    assert client.put('/api/device-api-access', headers=owner, json={
        'scope': 'isp_manager', 'target_id': '4', 'username': 'device-reader',
        'enabled': False}).status_code == 200
    assert client.get(PATH, headers=owner, params=QUERY).status_code == 409


def test_routeros_readings_filter_secrets_and_only_monitor_commands():
    paths = []
    def respond(request):
        path = request.url.path
        paths.append((request.method, path))
        if path == '/':
            assert 'authorization' not in request.headers
            return httpx.Response(200, text='MikroTik RouterOS')
        assert request.headers['authorization'].startswith('Basic ')
        if request.method == 'POST':
            assert path.endswith('/monitor')
            assert json.loads(request.content)['once'] == ''
        if path == '/rest/interface/ethernet':
            data = [{'.id': '*1', 'name': 'ether1'}, {'.id': '*2', 'name': 'ether2'}]
        elif path == '/rest/interface/ethernet/monitor':
            data = [{'status': 'link-ok', 'rate': '1Gbps'}] if json.loads(request.content)['numbers'] == '*1' else [{'status': 'no-link'}]
        elif path == '/rest/interface/wireless':
            data = [{'.id': '*3', 'name': 'wlan1', 'ssid': 'AirLink'}]
        elif path == '/rest/interface/wireless/monitor':
            data = [{'status': 'connected-to-ess', 'signal-strength': '-61dBm'}]
        elif path.endswith('registration-table'):
            data = []
        elif path == '/rest/interface/pppoe-client':
            assert 'password' not in request.url.query.decode()
            data = [{'.id': '*4', 'name': 'pppoe-out1', 'interface': 'wlan1', 'user': 'subscriber', 'password': 'NEVER-EXPOSE'}]
        elif path == '/rest/interface/pppoe-client/monitor':
            data = [{'status': 'connected', 'uptime': '2h', 'local-address': '10.2.3.4', 'remote-address': '10.2.3.1', 'password': 'NEVER-EXPOSE'}]
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=data)
    result = asyncio.run(online_device.collect('10.2.3.4', {
        'api_username': 'reader', 'api_password': 'secret', 'protocol': 'both'}, httpx.MockTransport(respond)))
    assert result['ethernet'][0]['speed_mbps'] == 1000
    assert result['ethernet'][1]['status'] == 'no-link'
    assert result['wireless'][0]['signal_dbm'] == -61
    assert result['pppoe'][0]['status'] == 'connected'
    assert result['pppoe'][0]['username'] == 'subscriber'
    assert 'NEVER-EXPOSE' not in json.dumps(result)
    assert all(method in ('GET', 'POST') for method, _ in paths)


def test_auth_failure_never_falls_back_to_http():
    schemes = []
    def respond(request):
        schemes.append(request.url.scheme)
        return httpx.Response(200, text='MikroTik') if request.url.path == '/' else httpx.Response(401)
    with pytest.raises(PermissionError):
        asyncio.run(online_device.collect('10.2.3.4', {
            'api_username': 'reader', 'api_password': 'secret', 'protocol': 'both'}, httpx.MockTransport(respond)))
    assert schemes == ['https', 'https']


def test_airos_https_fallback_and_supported_readings():
    def respond(request):
        if request.url.scheme == 'https':
            raise httpx.ConnectError('TLS unavailable', request=request)
        if request.url.path == '/':
            return httpx.Response(302, headers={'location': '/login.cgi'})
        if request.url.path == '/login.cgi' and request.method == 'GET':
            assert 'authorization' not in request.headers
            return httpx.Response(200, text='Ubiquiti airOS')
        if request.url.path == '/login.cgi':
            assert request.method == 'POST'
            return httpx.Response(302)
        if request.url.path == '/status.cgi':
            return httpx.Response(200, json={
                'wireless': {'mode': 'sta', 'signal': -65, 'essid': 'Customer-SSID'},
                'interfaces': [{'ifname': 'eth0', 'status': {'plugged': 1, 'speed': 100}}],
                'password': 'never-return-this'})
        pytest.fail('Unexpected device request')
    result = asyncio.run(online_device.collect('10.2.3.4', {
        'api_username': 'reader', 'api_password': 'secret', 'protocol': 'both'}, httpx.MockTransport(respond)))
    assert result['wireless'][0]['ssid'] == 'Customer-SSID'
    assert result['wireless'][0]['signal_dbm'] == -65
    assert result['ethernet'][0]['speed_mbps'] == 100
    assert result['pppoe'] == [] and result['pppoe_note']
    assert 'never-return-this' not in json.dumps(result)


@pytest.mark.parametrize(('login_page', 'model', 'expected_vendor'), [
    ('<title>NanoStation M5</title>', 'NanoStation M5', 'ubiquiti_m5'),
    ('<title>PowerBeam 5AC</title>', 'PowerBeam 5AC 400', 'ubiquiti_ac'),
])
def test_airmax_m5_and_ac_model_login_pages(login_page, model, expected_vendor):
    calls = []
    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/':
            return httpx.Response(200, text=login_page)
        if request.url.path == '/login.cgi':
            body = request.read()
            assert b'reader' in body and b'secret' in body and b'/status.cgi' in body
            return httpx.Response(302, headers={'set-cookie': 'AIROS_SESSION=verified; Path=/'})
        if request.url.path == '/status.cgi':
            assert request.headers.get('cookie') == 'AIROS_SESSION=verified'
            return httpx.Response(200, json={
                'host': {'devmodel': model, 'fwversion': 'test'},
                'wireless': {'mode': 'sta', 'signal': -62, 'essid': 'AirLink'},
                'interfaces': [],
            })
        pytest.fail('Unexpected device request')
    result = asyncio.run(online_device.collect_once('10.2.3.4', {
        'api_username': 'reader', 'api_password': 'secret', 'protocol': 'http',
    }, httpx.MockTransport(respond)))
    assert result['detected_vendor'] == expected_vendor
    assert result['groups']['System'][0]['device_model'] == model
    assert calls == [('GET', '/'), ('POST', '/login.cgi'), ('GET', '/status.cgi')]


def test_public_redirect_cannot_send_credentials_to_another_host():
    calls = []
    def respond(request):
        calls.append(str(request.url))
        assert 'authorization' not in request.headers
        return httpx.Response(302, headers={'location': 'http://other.example/login.cgi'})
    with pytest.raises(RuntimeError):
        asyncio.run(online_device.collect('10.2.3.4', {
            'api_username': 'reader', 'api_password': 'secret', 'protocol': 'http'}, httpx.MockTransport(respond)))
    assert calls == ['http://10.2.3.4/']


MANUAL = {**QUERY, 'login': {'username': 'temporary-device-user', 'password': 'temporary-device-secret'}}
CHANGE = {'menu': 'wireless', 'radio_id': '*1', 'previous_ssid': 'Before', 'ssid': 'After'}


def test_manual_login_needs_live_session_but_not_saved_credentials(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    calls = []
    monkeypatch.setattr(sas4_reports, 'fetch_managers', lambda *a: pytest.fail('Manual login must not need manager credentials'))
    async def collect(address, config):
        calls.append(config)
        assert config['api_password'] == MANUAL['login']['password']
        return {'vendor': 'MikroTik', 'wireless': []}
    monkeypatch.setattr(online_device, 'collect', collect)
    result = client.post(PATH + '/login', headers=owner, json=MANUAL)
    assert result.status_code == 200, result.text
    assert result.json()['credential_source'] == 'Temporary login'
    assert 'temporary-device' not in result.text
    for bad in ({'ip_address': '10.2.3.9'}, {'session_id': 'stale'}, {'username': 'wrong'}):
        assert client.post(PATH + '/login', headers=owner, json={**MANUAL, **bad}).status_code == 409
    assert len(calls) == 1
    from airlink.db import SessionLocal
    from airlink.models import DeviceLoginProfile
    from sqlalchemy import select
    with SessionLocal() as db:
        assert list(db.scalars(select(DeviceLoginProfile))) == []


def test_manual_login_read_permission_and_settings_write_permission(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    mid, manager = user(client, owner, 'manager', 'device-reader')
    client.put('/api/integrations/sas4', headers=manager, json={'username': 'radius-reader', 'password': 'sas-secret'}).raise_for_status()
    client.put('/api/users/' + mid + '/sections', headers=owner,
               json={'sections': ['isp_card'], 'editable_sections': []}).raise_for_status()
    async def collect(*args):
        return {'vendor': 'MikroTik'}
    monkeypatch.setattr(online_device, 'collect', collect)
    writes = []
    monkeypatch.setattr(online_device.device_management, 'run', lambda address, config, change: writes.append(change) or {'status': 'accepted'})
    assert client.post(PATH + '/login', headers=manager, json=MANUAL).status_code == 200
    assert client.put(PATH + '/settings', headers=manager, json={**MANUAL, 'change': CHANGE}).status_code == 403
    assert not writes
    client.put('/api/users/' + mid + '/sections', headers=owner,
               json={'sections': ['isp_card'], 'editable_sections': ['isp_card']}).raise_for_status()
    result = client.put(PATH + '/settings', headers=manager, json={**MANUAL, 'change': CHANGE})
    assert result.status_code == 200, result.text
    assert writes == [CHANGE]
    assert client.put(PATH + '/settings', headers=owner, json={**MANUAL, 'session_id': 'stale', 'change': CHANGE}).status_code == 409
    assert len(writes) == 1
    for bad in ({'ssid': 'x\ny'}, {'ssid': 'é'*17}, {'radio_id': '../system'}, {'menu': 'system'}):
        assert client.put(PATH + '/settings', headers=owner, json={**MANUAL, 'change': {**CHANGE, **bad}}).status_code == 422
    client.put('/api/users/' + mid + '/sections', headers=owner, json={'sections': []}).raise_for_status()
    assert client.post(PATH + '/login', headers=manager, json=MANUAL).status_code == 403


def test_ubiquiti_save_requires_restart_action(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    from airlink import airos_management
    monkeypatch.setattr(airos_management, 'connect', lambda *a: pytest.fail('Must not write without explicit restart action'))
    request = {**MANUAL, 'login': {**MANUAL['login'], 'transport': 'airos_ssh'}, 'change': CHANGE}
    assert client.put(PATH + '/settings', headers=owner, json=request).status_code == 422


def test_native_write_checks_stale_and_controller_settings(monkeypatch):
    writes, state = [], {'.id': '*1', 'ssid': 'Before'}
    class Connection:
        def __init__(self, *a): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def read(self, *a): return [state]
        async def command(self, *a): writes.append(a)
    monkeypatch.setattr(online_device.routeros_native, 'Connection', Connection)
    assert asyncio.run(online_device.native_change('10.2.3.4', {}, CHANGE)) == {'status': 'accepted'}
    assert writes == [('/interface/wireless/set', {'.id': '*1', 'ssid': 'After'})]
    state['ssid'] = 'Changed'
    with pytest.raises(online_device.device_management.ManagementError):
        asyncio.run(online_device.native_change('10.2.3.4', {}, CHANGE))
    state.update(ssid='Before', dynamic='true')
    with pytest.raises(online_device.device_management.ManagementError):
        asyncio.run(online_device.native_change('10.2.3.4', {}, CHANGE))
    assert len(writes) == 1


def test_validation_errors_never_echo_temporary_password(client, owner):
    result = client.post(PATH + '/login', headers=owner, json={**MANUAL, 'profile_id': 'conflicting-profile'})
    assert result.status_code == 422
    assert MANUAL['login']['password'] not in result.text
    result = client.post(PATH + '/login', headers=owner,
        json={**MANUAL, 'login': {**MANUAL['login'], 'password': 'PRIVATE' * 200}})
    assert result.status_code == 422 and 'PRIVATE' not in result.text


def test_manual_login_requires_tls_verification(client, owner):
    result = client.post(PATH + '/login', headers=owner, json={
        **MANUAL, 'login': {**MANUAL['login'], 'verify_tls': False}})
    assert result.status_code == 422
    assert MANUAL['login']['password'] not in result.text
