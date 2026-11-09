import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from airlink import customer_probes as probes, device_api, sas4
from airlink.db import SessionLocal
from airlink.models import CustomerProbeSettings, User
from airlink.security import cipher
from test_api import user
from monitoring import snmp
LOGIN_CONFIG = {**probes.DEFAULTS, 'api_username':'reader', 'api_password':'private-api'}




def test_device_access_secrets_scoped_and_encrypted(client, owner):
    manager_id, manager = user(client, owner, 'manager')
    _, viewer = user(client, owner, 'viewer')
    client.post('/api/snmp-profiles', headers=owner, json={'name':'Inventory', 'version':'2c', 'community':'owner-only'})
    path = '/api/integrations/sas4/device-access'
    body = {'community': 'private-snmp', 'api_username': 'monitor', 'api_password': 'private-api'}
    saved = client.put(path, headers=owner, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['has_community'] and saved.json()['has_api_password']
    assert 'private-' not in saved.text
    assert 'private-' not in client.get(path, headers=owner).text
    assert client.get(path, headers=manager).status_code == 403
    assert client.get(path, headers=viewer).status_code == 403
    assert client.put(path, headers=viewer, json=body).status_code == 403
    with SessionLocal() as db:
        saved = db.scalar(select(CustomerProbeSettings))
        assert 'private-' not in saved.encrypted_settings
        assert json.loads(cipher().decrypt(saved.encrypted_settings.encode()))['api_password'] == 'private-api'
        assert probes.configuration(db, db.get(User, manager_id))['snmp_candidates'] == []
        owner_user = db.scalar(select(User).where(User.role == 'owner'))
        assert probes.configuration(db, owner_user)['snmp_candidates'] == [
            {'version': '2c', 'community': 'private-snmp'},
            {'version': '1', 'community': 'private-snmp'},
        ]
    disabled = client.put(path, headers=manager, json={'try_public_snmp':False})
    assert disabled.status_code == 403
    with SessionLocal() as db:
        assert probes.configuration(db, db.get(User, manager_id))['snmp_candidates'] == []
    assert client.put(path, headers=owner, json={'api_username':'changed'}).status_code == 422
    saved = client.put(path, headers=owner, json={'api_username':'monitor', 'community':None})
    assert saved.json()['has_community'] and saved.json()['has_api_password']


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1',
    '0.0.0.0', '224.0.0.1', 'fe80::1', 'localhost', 'http://192.168.1.1', None, 1])
def test_discovery_rejects_non_customer_addresses(address):
    assert probes.valid_address(address) is None




def test_routeros_api_reads_only_monitoring_and_does_not_follow_redirects():
    requests=[]
    def transport(request):
        requests.append(request)
        path=request.url.path
        if path == '/': return httpx.Response(200, text='MikroTik RouterOS')
        assert request.headers.get('authorization', '').startswith('Basic ')
        if path == '/rest/interface/ethernet': return httpx.Response(200,json=[{'.id':'*1','name':'ether1'}])
        if path == '/rest/interface/ethernet/monitor':
            assert json.loads(request.content) == {'numbers':'*1','once':''}
            return httpx.Response(200,json=[{'status':'link-ok','rate':'1Gbps'}])
        if path == '/rest/interface/wireless/registration-table':
            return httpx.Response(200,json=[{'signal-strength':'-62dBm@54Mbps'}])
        raise AssertionError(path)
    result=asyncio.run(device_api.collect_api('192.168.1.1', {'api_username':'read','api_password':'test'}, transport=httpx.MockTransport(transport)))
    assert result['ethernet_links'] == [{'name':'ether1','speed_mbps':1000}]
    assert result['signal_dbm'] == -62
    assert requests[0].headers.get('authorization') is None
    requests.clear()
    def redirect(request):
        requests.append(request)
        return httpx.Response(302,headers={'location':'http://127.0.0.1/secret'})
    with pytest.raises(RuntimeError):
        asyncio.run(device_api.collect_api('192.168.1.1', {'api_username':'read','api_password':'test'}, transport=httpx.MockTransport(redirect)))
    assert len(requests)==1 and 'authorization' not in requests[0].headers


def test_airos_api_station_and_no_ap_signal():
    data={'wireless':{'mode':'sta-ptmp','signal':-65}, 'interfaces':[
        {'ifname':'eth0','status':{'plugged':1,'speed':100}},
        {'ifname':'ath0','status':{'plugged':1,'speed':300}}]}
    def transport(request):
        if request.url.path == '/': return httpx.Response(200,text='airOS Ubiquiti')
        if request.url.path == '/login.cgi':
            assert request.method=='POST'
            return httpx.Response(302,headers={'set-cookie':'AIROS_SESSIONID=test; Path=/', 'location':'/status.cgi'})
        assert request.url.path == '/status.cgi' and 'AIROS_SESSIONID=test' in request.headers['cookie']
        return httpx.Response(200,json=data)
    result=asyncio.run(device_api.collect_api('192.168.1.20',{'api_username':'read','api_password':'test'},transport=httpx.MockTransport(transport)))
    assert result['ethernet_links']==[{'name':'eth0','speed_mbps':100}]
    assert result['signal_dbm']==-65
    data['wireless']['mode']='ap'
    assert device_api.airos_values(data)['signal_dbm'] is None


def test_background_cache_is_nonblocking_deduplicated_and_account_scoped(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    async def fake_probe(address, config):
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        return {'ethernet_links':[{'name':'eth0','speed_mbps':100}], 'signal_dbm':-60,
                'telemetry_status':'available','telemetry_source':'RouterOS API'}
    monkeypatch.setattr(probes,'probe',fake_probe)
    monkeypatch.setattr(probes,'configuration',lambda db,user:{**LOGIN_CONFIG, 'snmp_candidates':[{'version':'2c','community':'private'}]})
    service=probes.ProbeService();service.start()
    account=SimpleNamespace(id='one')
    def result(): return {'clients':[{'username':'customer','session_id':1,'ip_address':'192.168.1.20'}]}
    try:
        assert service.enrich(None,account,result())['clients'][0]['telemetry_status']=='connecting'
        assert entered.wait(1)
        service.enrich(None,account,result())
        assert len(service.pending)==1
        release.set()
        service.pool.shutdown(wait=True)
        cached=service.enrich(None,account,result())['clients'][0]
        assert cached['signal_dbm']==-60
        assert all(key[0]=='one' for key in service.cache)
        # Changing session ID does not reuse another customer's cached reading.
        assert next(iter(service.cache))[2]=='1'
    finally:
        release.set();service.stop()


@pytest.mark.parametrize('oid,vendor', [('1.3.6.1.4.1.14988.1','mikrotik'),('1.3.6.1.4.1.10002.1','ubiquiti'),('1.3.6.1.4.1.41112.1','ubiquiti')])
@pytest.mark.parametrize('link_only', [False, True])
def test_snmp_detects_vendor(monkeypatch,oid,vendor,link_only):
    monkeypatch.setattr(snmp.UdpTransportTarget,'create',AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp,'get_cmd',AsyncMock(side_effect=[(None,0,0,[(snmp.UPTIME,100)]),(None,0,0,[('oid',oid)])]))
    tables=AsyncMock(return_value={});monkeypatch.setattr(snmp,'read_table',tables)
    values=asyncio.run(snmp.collect('192.168.1.1',{'version':'2c','community':'private'},0,vendor='auto',link_only=link_only))
    assert values['detected_vendor']==vendor
    called = {call.args[3] for call in tables.call_args_list}
    expected = {snmp.WIRELESS_TABLES[vendor]['signal_dbm']} if link_only else set(snmp.WIRELESS_TABLES[vendor].values())
    assert expected.issubset(called)
    if link_only:
        assert not {snmp.TABLES['cpu'], snmp.TABLES['if_rx_octets'], snmp.FALLBACK_TABLES['if_tx32']} & called
        assert snmp.TABLES['if_type'] in called and snmp.TABLES['if_speed_mbps'] in called














@pytest.mark.parametrize('page,expected', [('MikroTik RouterOS','mikrotik'), ('airOS Ubiquiti','ubiquiti'), ('Mimosa C5','mimosa'), ('Login','generic')])
def test_public_device_brand_detection_sends_no_credentials(page, expected):
    def handler(request):
        assert 'authorization' not in request.headers
        if request.url.path == '/':
            return httpx.Response(302, headers={'Location':'/login'})
        assert request.url.path == '/login'
        return httpx.Response(200, text=page)
    assert asyncio.run(device_api.detect_vendor('192.0.2.1', {**probes.DEFAULTS, 'allow_http': False},
        transport=httpx.MockTransport(handler))) == expected


def test_public_device_detection_rejects_external_redirects():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location':'http://127.0.0.1/'})
    assert asyncio.run(device_api.detect_vendor('192.0.2.1', {**probes.DEFAULTS, 'allow_http': False},
        transport=httpx.MockTransport(handler))) == 'generic'
    assert len(calls) == 1


def test_refresh_retains_readings_until_replaced_and_keeps_session_isolation(monkeypatch):
    config = {**LOGIN_CONFIG, 'snmp_candidates': [{'version': '2c', 'community': 'public'}]}
    monkeypatch.setattr(probes, 'configuration', lambda db, user: config)
    service = probes.ProbeService()
    submitted = []
    service.pool = SimpleNamespace(submit=lambda *args: submitted.append(args))
    account = SimpleNamespace(id='owner')
    key = ('owner', '192.0.2.1', '1', 'customer', probes.hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())
    service.cache[key] = (probes.time.monotonic() - 31, {
        'ethernet_links': [{'name': 'eth0', 'speed_mbps': 100}], 'signal_dbm': -60,
        'telemetry_status': 'available', 'telemetry_source': 'RouterOS API'})
    def rows(session=1):
        return {'clients': [{'username': 'customer', 'session_id': session, 'ip_address': '192.0.2.1'}]}
    refreshing = service.enrich(None, account, rows())['clients'][0]
    assert refreshing['signal_dbm'] == -60 and refreshing['ethernet_links'][0]['speed_mbps'] == 100
    assert refreshing['telemetry_status'] == 'connecting'
    service.enrich(None, account, rows())
    assert len(submitted) == 1
    monkeypatch.setattr(probes, 'probe', AsyncMock(return_value={
        'ethernet_links': [], 'signal_dbm': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}))
    service.run(key, '192.0.2.1', config)
    failed = service.enrich(None, account, rows())['clients'][0]
    assert failed['signal_dbm'] == -60 and failed['telemetry_status'] == 'unreachable'
    assert failed['telemetry_stale_fields'] == ['ethernet_links', 'signal_dbm']
    other = service.enrich(None, account, rows(2))['clients'][0]
    assert other.get('signal_dbm') is None and other['telemetry_status'] == 'connecting'
    monkeypatch.setattr(probes, 'probe', AsyncMock(return_value={
        'ethernet_links': [{'name': 'eth0', 'speed_mbps': 1000}], 'signal_dbm': -55,
        'telemetry_status': 'available', 'telemetry_source': 'RouterOS API'}))
    service.run(key, '192.0.2.1', config)
    updated = service.enrich(None, account, rows())['clients'][0]
    assert updated['signal_dbm'] == -55 and updated['ethernet_links'][0]['speed_mbps'] == 1000
    assert updated['telemetry_stale_fields'] == []


def test_authenticated_readings_do_not_use_snmp_or_ping(monkeypatch):
    from airlink import online_device_auto
    collect = AsyncMock(return_value={'vendor':'MikroTik', 'detected_vendor':'mikrotik',
        'connection': {'transport':'routeros'},
        'ethernet':[{'name':'ether1','status':'link-ok','speed_mbps':1000}, {'name':'ether2','status':'link-ok','speed_mbps':100}],
        'wireless':[{'ssid':'Customer WiFi','signal_dbm':-62}]})
    monkeypatch.setattr(online_device_auto, 'detect_and_connect', collect)
    monkeypatch.setattr(snmp, 'collect', AsyncMock(side_effect=AssertionError('No SNMP permitted')))
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(side_effect=AssertionError('No ping permitted')))
    result=asyncio.run(probes.probe('192.168.1.20', LOGIN_CONFIG))
    assert result['ethernet_links'] == [{'name':'ether1','speed_mbps':1000}]
    assert result['signal_dbm']==-62 and result['ssid']=='Customer WiFi'
    assert result['telemetry_source']=='RouterOS API'
    assert collect.call_args.args[1]['api_password']=='private-api'
    assert collect.call_args.args[1]['background'] is True
    assert collect.call_args.args[1]['telemetry_only'] is True


def test_snmp_v2_then_v1_auto_detects_vendor_and_readings(monkeypatch):
    from airlink import online_device_auto
    api = AsyncMock(side_effect=AssertionError('SNMP success must not send the device password'))
    monkeypatch.setattr(online_device_auto, 'detect_and_connect', api)
    values = {
        'detected_vendor': 'ubiquiti_m5',
        'interfaces': {'1': {'name': 'eth0', 'type': 6, 'status': 1, 'speed_mbps': 100}},
        'wireless': {'station_signal_dbm': {'1': -61}, 'ssid': {'1': 'AirLink-M5'}},
    }
    collect = AsyncMock(side_effect=[RuntimeError('v2 unavailable'), values])
    monkeypatch.setattr(snmp, 'collect', collect)
    config = {**probes.DEFAULTS, 'snmp_candidates': [
        {'version': '2c', 'community': 'private'},
        {'version': '1', 'community': 'private'},
    ]}
    result = asyncio.run(probes.probe('192.168.1.20', config))
    assert [call.args[1]['version'] for call in collect.call_args_list] == ['2c', '1']
    assert result['detected_vendor'] == 'ubiquiti_m5'
    assert result['vendor_label'] == 'Ubiquiti airMAX M5'
    assert result['ethernet_links'] == [{'name': 'eth0', 'speed_mbps': 100}]
    assert result['signal_dbm'] == -61 and result['ssid'] == 'AirLink-M5'
    assert result['telemetry_source'] == 'SNMP v1'
    api.assert_not_awaited()


def test_snmp_failure_falls_back_to_saved_device_login(monkeypatch):
    from airlink import online_device_auto
    monkeypatch.setattr(snmp, 'collect', AsyncMock(side_effect=RuntimeError('unavailable')))
    api = AsyncMock(return_value={'vendor': 'MikroTik', 'detected_vendor': 'mikrotik',
        'connection': {'transport': 'routeros'},
        'ethernet': [{'name': 'ether1', 'status': 'link-ok', 'speed_mbps': 1000}],
        'wireless': [{'ssid': 'AirLink', 'signal_dbm': -58}]})
    monkeypatch.setattr(online_device_auto, 'detect_and_connect', api)
    config = {**LOGIN_CONFIG, 'snmp_candidates': [
        {'version': '2c', 'community': 'private'},
        {'version': '1', 'community': 'private'},
    ]}
    result = asyncio.run(probes.probe('192.168.1.20', config))
    assert result['detected_vendor'] == 'mikrotik'
    assert result['ethernet_links'][0]['speed_mbps'] == 1000
    assert result['signal_dbm'] == -58 and result['ssid'] == 'AirLink'
    assert result['telemetry_source'] == 'RouterOS API'


def test_missing_or_rejected_password_never_uses_snmp_fallback(monkeypatch):
    from airlink import online_device_auto
    collect=AsyncMock(side_effect=PermissionError())
    monkeypatch.setattr(online_device_auto, 'detect_and_connect',collect)
    result=asyncio.run(probes.probe('192.168.1.20',probes.DEFAULTS))
    assert result['telemetry_status']=='credentials_required'
    collect.assert_not_awaited()
    result=asyncio.run(probes.probe('192.168.1.20',LOGIN_CONFIG))
    assert result['telemetry_status']=='authentication_failed'
    assert collect.await_count==1


def test_online_user_does_not_reuse_inventory_snmp_data(monkeypatch):
    monkeypatch.setattr(probes,'configuration',lambda *a:probes.DEFAULTS)
    row={'username':'customer','ip_address':'192.168.1.20','signal_dbm':-60,'ssid':'old',
         'telemetry_source':'SNMP','telemetry_status':'available'}
    result=probes.ProbeService().enrich(None,SimpleNamespace(id='one'),{'clients':[row]})['clients'][0]
    assert result['signal_dbm'] is None and result['ssid'] is None
    assert result['telemetry_source'] is None and result['telemetry_status']=='credentials_required'


def test_invalid_device_password_is_not_echoed(client, owner):
    result=client.put('/api/integrations/sas4/device-access',headers=owner,
        json={'api_username':'device','api_password':'DO-NOT-ECHO-'*100})
    assert result.status_code==422 and 'DO-NOT-ECHO' not in result.text


def test_read_only_enrichment_never_starts_device_checks(monkeypatch):
    monkeypatch.setattr(probes, 'configuration', lambda *a: LOGIN_CONFIG)
    service = probes.ProbeService()
    service.pool = SimpleNamespace(submit=lambda *args: pytest.fail('Page queued a device connection'))
    account = SimpleNamespace(id='account')
    result = service.enrich(None, account, {'clients': [
        {'username': 'user', 'session_id': 1, 'ip_address': '192.168.1.1'}]}, schedule=False)
    assert result['clients'][0]['telemetry_status'] == 'pending'
    assert not service.pending
