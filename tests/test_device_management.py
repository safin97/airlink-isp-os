import asyncio
import httpx
import pytest
from airlink import device_management as management
from airlink.db import SessionLocal
from airlink.models import Device
from test_api import user, tower, device

CONFIG = {'enabled': True, 'api_username': 'reader', 'api_password': 'secret-password',
          'protocol': 'https', 'port': None, 'verify_tls': True}


@pytest.mark.parametrize('menu,field', [('wireless','ssid'), ('wifi','configuration.ssid'), ('wifiwave2','configuration.ssid')])
def test_ssid_change_writes_only_selected_interface_and_field(menu, field):
    writes = []
    def handle(request):
        assert request.url.host == '192.0.2.1'
        if request.method == 'GET':
            assert request.url.path == '/rest/interface/' + menu
            return httpx.Response(200, json=[{'.id':'*1', 'name':'radio1', field:'Old'}])
        writes.append(request)
        return httpx.Response(200, json={'.id':'*1', field:'New', 'password':'must-not-return'})
    change = {'menu':menu, 'radio_id':'*1', 'previous_ssid':'Old', 'ssid':'New'}
    result = asyncio.run(management.wireless('192.0.2.1', CONFIG, change, httpx.MockTransport(handle)))
    assert result == {'status':'accepted'}
    assert len(writes) == 1 and writes[0].method == 'PATCH'
    assert writes[0].url.path == '/rest/interface/'+menu+'/*1'
    import json
    assert json.loads(writes[0].content) == {field:'New'}


@pytest.mark.parametrize('scenario', ['stale', 'controller', 'auth', 'timeout'])
def test_blocked_or_uncertain_changes_are_not_retried(scenario):
    writes = []
    def handle(request):
        if request.method == 'GET':
            if scenario == 'auth': return httpx.Response(403)
            return httpx.Response(200, json=[{'.id':'*1', 'name':'radio1', 'ssid':'Changed' if scenario == 'stale' else 'Old',
                'configuration.manager':'capsman' if scenario == 'controller' else 'local'}])
        writes.append(request)
        raise httpx.ReadTimeout('secret response must not leak')
    with pytest.raises(management.ManagementError) as exc:
        asyncio.run(management.wireless('192.0.2.1', CONFIG,
            {'menu':'wireless', 'radio_id':'*1', 'previous_ssid':'Old', 'ssid':'New'}, httpx.MockTransport(handle)))
    assert 'secret response' not in str(exc.value)
    assert len(writes) == (1 if scenario == 'timeout' else 0)


def test_reading_radios_filters_secrets_and_handles_multiple_packages():
    def handle(request):
        if request.url.path != '/rest/interface/wifi': return httpx.Response(404)
        return httpx.Response(200, json=[{'.id':'*A', 'name':'wifi1', 'configuration.ssid':'Office',
            'security.passphrase':'secret', 'password':'private'}])
    result = asyncio.run(management.wireless('192.0.2.1', CONFIG, transport=httpx.MockTransport(handle)))
    assert result == [{'menu':'wifi','id':'*A','name':'wifi1','ssid':'Office','editable':True,'reason':None}]


def test_management_permissions_scope_validation_and_unsupported_vendor(client, owner, monkeypatch):
    manager_id, manager = user(client, owner, 'manager', 'wireless-editor')
    tid = tower(client, owner, 'Allowed', manager=manager_id)
    did = device(client, owner, tid)
    other = device(client, owner, tower(client, owner, 'Other'), '192.0.2.2')
    with SessionLocal() as db:
        db.get(Device, did).vendor = 'mikrotik'; db.commit()
    calls = []
    def run(address, config, change=None):
        calls.append(change)
        return {'status':'accepted'} if change else [{'menu':'wireless','id':'*1','name':'wlan1','ssid':'Old','editable':True}]
    monkeypatch.setattr(management, 'run', run)
    path = '/api/devices/'+did+'/wireless-settings'
    payload = {'menu':'wireless','radio_id':'*1','previous_ssid':'Old','ssid':'New'}
    client.put('/api/users/'+manager_id+'/sections', headers=owner,
        json={'sections':['towers'],'editable_sections':[]}).raise_for_status()
    assert client.get(path, headers=manager).status_code == 200
    assert client.put(path, headers=manager, json=payload).status_code == 403
    assert client.get('/api/devices/'+other+'/wireless-settings', headers=manager).status_code == 404
    assert all(call is None for call in calls)
    client.put('/api/users/'+manager_id+'/sections', headers=owner,
        json={'sections':['towers'],'editable_sections':['towers']}).raise_for_status()
    assert client.put(path, headers=manager, json=payload).status_code == 200
    assert calls[-1] == payload
    for bad in ({'radio_id':'../system'}, {'menu':'system'}, {'ssid':'x'*33}, {'ssid':'é'*17}, {'ssid':'bad\nssid'}):
        assert client.put(path, headers=owner, json={**payload, **bad}).status_code == 422
    with SessionLocal() as db:
        db.get(Device, did).vendor = 'mimosa'; db.commit()
    before = len(calls)
    assert client.get(path, headers=owner).json()['supported'] is False
    assert client.put(path, headers=owner, json=payload).status_code == 422
    assert len(calls) == before


def test_both_protocols_fall_back_before_single_write():
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.scheme == 'https':
            raise httpx.ConnectError('HTTPS unavailable')
        if request.method == 'GET':
            return httpx.Response(200, json=[{'.id':'*1','name':'wlan1','ssid':'Old'}])
        return httpx.Response(200, json={})
    result = asyncio.run(management.wireless('192.0.2.1', {**CONFIG,'protocol':'both'},
        {'menu':'wireless','radio_id':'*1','previous_ssid':'Old','ssid':'New'}, httpx.MockTransport(handle)))
    assert result == {'status':'accepted'}
    assert [(r.url.scheme,r.method,r.url.port or (443 if r.url.scheme == 'https' else 80)) for r in requests] == [
        ('https','GET',443),('http','GET',80),('http','PATCH',80)]


@pytest.mark.parametrize('failure', ['authentication', 'uncertain_write'])
def test_both_protocols_do_not_retry_rejected_login_or_uncertain_write(failure):
    requests = []
    def handle(request):
        requests.append(request)
        if failure == 'authentication': return httpx.Response(401)
        if request.method == 'GET':
            return httpx.Response(200, json=[{'.id':'*1','name':'wlan1','ssid':'Old'}])
        raise httpx.ReadTimeout('write response lost')
    with pytest.raises(management.ManagementError):
        asyncio.run(management.wireless('192.0.2.1', {**CONFIG,'protocol':'both'},
            {'menu':'wireless','radio_id':'*1','previous_ssid':'Old','ssid':'New'}, httpx.MockTransport(handle)))
    assert all(r.url.scheme == 'https' for r in requests)
    assert len([r for r in requests if r.method == 'PATCH']) == (1 if failure == 'uncertain_write' else 0)
