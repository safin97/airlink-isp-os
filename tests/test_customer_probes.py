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


@pytest.fixture(autouse=True)
def no_background_network(monkeypatch):
    monkeypatch.setattr(probes, 'reachable', AsyncMock(return_value=False))
    monkeypatch.setattr(probes, 'detect_vendor', AsyncMock(return_value='generic'))


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
    assert not client.get(path, headers=manager).json()['has_api_password']
    assert client.get(path, headers=viewer).status_code == 403
    assert client.put(path, headers=viewer, json=body).status_code == 403
    with SessionLocal() as db:
        saved = db.scalar(select(CustomerProbeSettings))
        assert 'private-' not in saved.encrypted_settings
        assert json.loads(cipher().decrypt(saved.encrypted_settings.encode()))['api_password'] == 'private-api'
        assert probes.configuration(db, db.get(User, manager_id))['snmp_candidates'] == [{'version':'2c','community':'public'}]
    disabled = client.put(path, headers=manager, json={'try_public_snmp':False})
    assert disabled.status_code == 200 and disabled.json()['try_public_snmp'] is False
    with SessionLocal() as db:
        assert probes.configuration(db, db.get(User, manager_id))['snmp_candidates'] == []
    assert client.put(path, headers=owner, json={'api_username':'changed'}).status_code == 422
    saved = client.put(path, headers=owner, json={'api_username':'monitor', 'community':None})
    assert saved.json()['has_community'] and saved.json()['has_api_password']


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1',
    '0.0.0.0', '224.0.0.1', 'fe80::1', 'localhost', 'http://192.168.1.1', None, 1])
def test_discovery_rejects_non_customer_addresses(address):
    assert probes.valid_address(address) is None


def test_snmp_version_fallback_and_api_fills_missing_signal(monkeypatch):
    calls = []
    async def collect(address, credentials, retries, vendor, link_only=False):
        assert link_only is True
        calls.append(credentials['version'])
        if credentials['version'] == '1': raise RuntimeError('No response')
        return {'snmp_up': True, 'detected_vendor': 'ubiquiti', 'interfaces': {
            '1': {'name':'eth0','type':6,'status':1,'speed_mbps':100}}}
    monkeypatch.setattr(snmp, 'collect', collect)
    api = AsyncMock(return_value={'ethernet_links':[], 'signal_dbm':-64, 'telemetry_source':'airOS API'})
    monkeypatch.setattr(probes, 'collect_api', api)
    config = {**probes.DEFAULTS, 'snmp_candidates':[{'version':'2c','community':'private'}],
              'api_username':'monitor','api_password':'private'}
    result = asyncio.run(probes.probe('192.168.1.20', config))
    assert calls == ['1', '2c']
    assert result['ethernet_links'][0]['speed_mbps'] == 100
    assert result['signal_dbm'] == -64
    assert result['telemetry_source'] == 'SNMP v2 + airOS API'
    api.assert_awaited_once()


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
                'telemetry_status':'available','telemetry_source':'SNMP v2'}
    monkeypatch.setattr(probes,'probe',fake_probe)
    monkeypatch.setattr(probes,'configuration',lambda db,user:{**probes.DEFAULTS, 'snmp_candidates':[{'version':'2c','community':'private'}]})
    service=probes.ProbeService();service.start()
    account=SimpleNamespace(id='one')
    def result(): return {'clients':[{'username':'customer','session_id':1,'ip_address':'192.168.1.20'}]}
    try:
        assert service.enrich(None,account,result())['clients'][0]['telemetry_status']=='checking'
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


def test_reachable_device_with_no_snmp_is_distinguished(monkeypatch):
    monkeypatch.setattr(probes, 'reachable', AsyncMock(return_value=True))
    monkeypatch.setattr(snmp, 'collect', AsyncMock(side_effect=RuntimeError('No SNMP response')))
    result = asyncio.run(probes.probe('192.0.2.1', {
        **probes.DEFAULTS, 'snmp_candidates': [{'version': '2c', 'community': 'public'}]}))
    assert result['device_reachable'] is True
    assert result['telemetry_status'] == 'snmp_unavailable'
    assert result['signal_dbm'] is None and result['ethernet_links'] == []


def test_slow_snmp_candidates_leave_time_for_api(monkeypatch):
    monkeypatch.setattr(probes, 'reachable', AsyncMock(return_value=False))
    monkeypatch.setattr(probes, 'SNMP_BUDGET', .02)
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(snmp, 'collect', slow)
    api = AsyncMock(return_value={'ethernet_links': [{'name': 'eth0', 'speed_mbps': 100}],
                                  'signal_dbm': -60, 'telemetry_source': 'airOS API'})
    monkeypatch.setattr(probes, 'collect_api', api)
    result = asyncio.run(probes.probe('192.0.2.1', {**probes.DEFAULTS,
        'snmp_candidates': [{'version': '2c', 'community': 'public'}],
        'api_username': 'read', 'api_password': 'private'}))
    api.assert_awaited_once()
    assert result['signal_dbm'] == -60 and result['device_reachable'] is True


def test_late_api_timeout_preserves_successful_snmp(monkeypatch):
    monkeypatch.setattr(probes, 'reachable', AsyncMock(return_value=True))
    monkeypatch.setattr(probes, 'PROBE_BUDGET', .03)
    monkeypatch.setattr(snmp, 'collect', AsyncMock(return_value={
        'snmp_up': True, 'interfaces': {'1': {'name':'ether1','type':6,'status':1,'speed_mbps':1000}}}))
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(probes, 'collect_api', slow)
    result = asyncio.run(probes.probe('192.0.2.1', {**probes.DEFAULTS,
        'snmp_candidates': [{'version':'2c','community':'public'}], 'api_username':'read','api_password':'private'}))
    assert result['ethernet_links'][0]['speed_mbps'] == 1000
    assert result['telemetry_status'] == 'available' and result['telemetry_source'] == 'SNMP v1'


def test_failed_direct_probe_preserves_partial_inventory_reading(monkeypatch):
    config = {**probes.DEFAULTS, 'snmp_candidates': [{'version':'2c','community':'public'}]}
    monkeypatch.setattr(probes, 'configuration', lambda db, user: config)
    service = probes.ProbeService()
    account = SimpleNamespace(id='owner')
    key = ('owner', '192.0.2.1', '1', 'customer', probes.hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())
    service.cache[key] = (probes.time.monotonic(), {'ethernet_links':[], 'signal_dbm':None,
        'telemetry_status':'unreachable', 'telemetry_source':None, 'device_reachable':False})
    row = {'username':'customer', 'session_id':1, 'ip_address':'192.0.2.1',
           'ethernet_links':[{'name':'eth0','speed_mbps':100}], 'signal_dbm':None,
           'telemetry_status':'available', 'telemetry_source':'airOS API', 'device_reachable':True}
    result = service.enrich(None, account, {'clients':[row]})['clients'][0]
    assert result['telemetry_status'] == 'available' and result['telemetry_source'] == 'airOS API'
    assert result['device_reachable'] is True


def test_snmp_fallback_order_includes_configured_v3_and_stops_on_success(monkeypatch):
    calls = []
    async def collect(address, credentials, *args, **kwargs):
        calls.append(credentials['version'])
        if credentials['version'] != '3':
            raise RuntimeError('No response')
        assert credentials['username'] == 'reader'
        return {'snmp_up': True, 'detected_vendor': 'mimosa', 'interfaces': {}}
    monkeypatch.setattr(snmp, 'collect', collect)
    config = {**probes.DEFAULTS, 'snmp_candidates': [
        {'version':'3','username':'reader','auth_key':'private-auth','priv_key':'private-key'},
        {'version':'2c','community':'public'}]}
    result = asyncio.run(probes.probe('192.0.2.1', config))
    assert calls == ['1','2c','3']
    assert result['vendor_label'] == 'Mimosa' and result['telemetry_source'] == 'SNMP v3'
    assert result['vendor_detection_source'] == 'SNMP'
    assert [c['version'] for c in probes.snmp_attempts([{'version':'2c','community':'public'}])] == ['1','2c']


def test_web_identity_is_retained_when_snmp_is_unavailable(monkeypatch):
    monkeypatch.setattr(probes, 'detect_vendor', AsyncMock(return_value='mikrotik'))
    monkeypatch.setattr(snmp, 'collect', AsyncMock(side_effect=RuntimeError('timeout')))
    result = asyncio.run(probes.probe('192.0.2.1', {**probes.DEFAULTS,
        'snmp_candidates':[{'version':'2c','community':'public'}]}))
    assert result['vendor_label'] == 'MikroTik'
    assert result['telemetry_status'] == 'snmp_unavailable'
    assert result['signal_dbm'] is None


@pytest.mark.parametrize('page,expected', [('MikroTik RouterOS','mikrotik'), ('airOS Ubiquiti','ubiquiti'), ('Mimosa C5','mimosa'), ('Login','generic')])
def test_public_device_brand_detection_sends_no_credentials(page, expected):
    def handler(request):
        assert 'authorization' not in request.headers
        if request.url.path == '/':
            return httpx.Response(302, headers={'Location':'/login'})
        assert request.url.path == '/login'
        return httpx.Response(200, text=page)
    assert asyncio.run(device_api.detect_vendor('192.0.2.1', probes.DEFAULTS,
        transport=httpx.MockTransport(handler))) == expected


def test_public_device_detection_rejects_external_redirects():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location':'http://127.0.0.1/'})
    assert asyncio.run(device_api.detect_vendor('192.0.2.1', probes.DEFAULTS,
        transport=httpx.MockTransport(handler))) == 'generic'
    assert len(calls) == 1
