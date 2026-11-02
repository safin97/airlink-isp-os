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
    async def collect(address, credentials, retries, vendor):
        calls.append(credentials['version'])
        if credentials['version'] == '2c': raise RuntimeError('No response')
        return {'snmp_up': True, 'detected_vendor': 'ubiquiti', 'interfaces': {
            '1': {'name':'eth0','type':6,'status':1,'speed_mbps':100}}}
    monkeypatch.setattr(snmp, 'collect', collect)
    api = AsyncMock(return_value={'ethernet_links':[], 'signal_dbm':-64, 'telemetry_source':'airOS API'})
    monkeypatch.setattr(probes, 'collect_api', api)
    config = {**probes.DEFAULTS, 'snmp_candidates':[{'version':'2c','community':'private'}],
              'api_username':'monitor','api_password':'private'}
    result = asyncio.run(probes.probe('192.168.1.20', config))
    assert calls == ['2c', '1']
    assert result['ethernet_links'][0]['speed_mbps'] == 100
    assert result['signal_dbm'] == -64
    assert result['telemetry_source'] == 'SNMP v1 + airOS API'
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
                'telemetry_status':'available','telemetry_source':'SNMP v2c'}
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
def test_snmp_detects_vendor(monkeypatch,oid,vendor):
    monkeypatch.setattr(snmp.UdpTransportTarget,'create',AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp,'get_cmd',AsyncMock(side_effect=[(None,0,0,[(snmp.UPTIME,100)]),(None,0,0,[('oid',oid)])]))
    tables=AsyncMock(return_value={});monkeypatch.setattr(snmp,'read_table',tables)
    values=asyncio.run(snmp.collect('192.168.1.1',{'version':'2c','community':'private'},0,vendor='auto'))
    assert values['detected_vendor']==vendor
    assert set(snmp.WIRELESS_TABLES[vendor].values()).issubset({call.args[3] for call in tables.call_args_list})
