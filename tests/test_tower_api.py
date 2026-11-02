import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import httpx
import pytest
from sqlalchemy import select
from airlink import device_api, tower_api
from airlink.db import SessionLocal
from airlink.models import TowerAPISettings, Device, Metric, now
from airlink.security import cipher
from monitoring import worker
from test_api import tower, device, user


async def poll(device_id):
    await worker.poll(device_id, asyncio.Semaphore(1))


def settings(**overrides):
    return {'name': 'North', 'api_enabled': True, 'api_username': 'monitor',
            'api_password': 'tower-private-password', **overrides}


def test_credentials_write_only_scoped_preserved_and_disabled(client, owner):
    mid, manager = user(client, owner, 'manager')
    _, viewer = user(client, owner, 'viewer')
    saved = client.post('/api/towers', headers=owner, json=settings(manager_id=mid))
    assert saved.status_code == 201, saved.text
    tid = saved.json()['id']
    assert saved.json()['has_api_password']
    for headers in (owner, manager, viewer):
        response = client.get('/api/towers', headers=headers)
        assert 'tower-private-password' not in response.text
        assert 'encrypted_credentials' not in response.text
        assert 'api_password' not in response.json()[0]
        if headers != owner:
            assert 'api_username' not in response.json()[0]
    with SessionLocal() as db:
        row = db.get(TowerAPISettings, tid)
        assert 'tower-private-password' not in row.encrypted_credentials
        assert json.loads(cipher().decrypt(row.encrypted_credentials.encode()))['api_password'] == 'tower-private-password'
    path = '/api/towers/' + tid
    # Regular manager edits preserve the owner's credentials.
    assert client.put(path, headers=manager, json={'name':'Renamed', 'manager_id':mid}).status_code == 200
    assert client.put(path, headers=manager, json=settings(manager_id=mid)).status_code == 403
    kept = client.put(path, headers=owner, json=settings(api_password=None, manager_id=mid))
    assert kept.status_code == 200 and kept.json()['has_api_password']
    assert client.put(path, headers=owner, json=settings(api_username='new', api_password=None)).status_code == 422
    assert client.put(path, headers=owner, json={'name':'North', 'api_enabled':False}).status_code == 200
    with SessionLocal() as db:
        assert tower_api.configuration(db, tid)['enabled'] is False
    assert client.delete(path, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(TowerAPISettings, tid) is None


@pytest.mark.parametrize('overrides', [{'api_password':None}, {'api_username':''}, {'api_port':0}, {'api_protocol':'ftp'}])
def test_invalid_api_configuration(client, owner, overrides):
    assert client.post('/api/towers', headers=owner, json=settings(**overrides)).status_code == 422


def test_routeros_inventory_resources_and_ap_signal(client):
    requests = []
    def transport(request):
        requests.append(request)
        assert request.url.port == 8443
        path = request.url.path
        if path == '/': return httpx.Response(200, text='RouterOS')
        if path == '/rest/interface/ethernet': return httpx.Response(200, json=[{'.id':'*1','name':'ether1'}])
        if path == '/rest/interface/ethernet/monitor':
            assert request.method == 'POST' and json.loads(request.content) == {'numbers':'*1', 'once':''}
            return httpx.Response(200, json=[{'status':'link-ok', 'rate':'1Gbps'}])
        assert request.method == 'GET'
        if path == '/rest/interface/wireless/registration-table':
            return httpx.Response(200, json=[{'signal-strength':'-60dBm'}, {'signal-strength':'-72dBm'}])
        if path == '/rest/system/resource':
            return httpx.Response(200, json={'cpu-load':'18', 'free-memory':'256', 'total-memory':'1024',
                'uptime':'1w2d3h4m5s', 'version':'7.20', 'board-name':'RouterBoard'})
        raise AssertionError(path)
    values = asyncio.run(device_api.collect_api('192.168.88.1', {
        'api_username':'monitor','api_password':'test','protocol':'https','port':8443},
        inventory=True, transport=httpx.MockTransport(transport)))
    assert values['cpu_percent'] == 18
    assert values['memory_percent'] == 75
    assert values['uptime_seconds'] == 788645
    assert values['ethernet_links'] == [{'name':'ether1','speed_mbps':1000}]
    assert values['signal_dbm'] is None  # AP readings aren't attributed to a single client.
    assert values['weakest_signal_dbm'] == -72 and values['wireless_clients'] == 2
    assert requests[0].headers.get('authorization') is None


def test_airos_inventory_fields_and_vendor_alias():
    data = {'host': {'cpuload':12,'uptime':7200,'totalram':1024,'freeram':256,
                     'fwversion':'v8.5','devmodel':'Rocket AC'},
            'wireless': {'mode':'sta-ptmp','signal':-63,'frequency':5800,'count':1},
            'interfaces':[{'ifname':'eth0','status':{'plugged':1,'speed':1000}}]}
    def transport(request):
        if request.url.path == '/': return httpx.Response(200)
        if request.url.path == '/login.cgi': return httpx.Response(200)
        return httpx.Response(200,json=data)
    values = asyncio.run(device_api.collect_api('192.168.1.20', {'api_username':'read','api_password':'test'},
        vendor='ubiquiti_ac', inventory=True, transport=httpx.MockTransport(transport)))
    assert values['memory_percent'] == 75 and values['cpu_percent'] == 12
    assert values['signal_dbm'] == -63 and values['radio_frequencies_mhz'] == [5800]
    assert values['device_model'] == 'Rocket AC'
    data['host'] = {'cpuload':'nan','uptime':-1,'totalram':1,'freeram':2}
    bad = device_api.airos_values(data, inventory=True)
    assert not {'memory_percent','cpu_percent','uptime_seconds'} & bad.keys()


@pytest.mark.parametrize('failure', [None, PermissionError('secret must not leak'), RuntimeError('secret must not leak')])
def test_inventory_poll_and_freshness(client, owner, monkeypatch, failure):
    saved = client.post('/api/towers', headers=owner, json=settings()).json()
    tid = saved['id']
    did = device(client, owner, tid)
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=False))
    probe = AsyncMock(side_effect=failure, return_value={'cpu_percent':24,'memory_percent':50,
        'ethernet_links':[{'name':'ether1','speed_mbps':1000}], 'signal_dbm':-60, 'telemetry_source':'RouterOS API'})
    monkeypatch.setattr(worker, 'collect_api', probe)
    asyncio.run(poll(did))
    result = client.get('/api/devices', headers=owner).json()[0]
    assert 'secret must not leak' not in json.dumps(result)
    assert 'tower-private-password' not in json.dumps(result)
    probe.assert_awaited_once()
    assert probe.call_args.kwargs['inventory'] is True
    if failure:
        assert result['api_status'] == ('authentication_failed' if isinstance(failure, PermissionError) else 'failed')
        assert 'cpu_percent' not in result['telemetry']
    else:
        assert result['api_status'] == 'connected' and result['status'] == 'online'
        assert result['telemetry']['cpu_percent'] == 24
        with SessionLocal() as db:
            metric = db.scalar(select(Metric).where(Metric.device_id == did))
            metric.collected_at = now() - timedelta(minutes=15)
            db.commit()
        stale = client.get('/api/devices', headers=owner).json()[0]
        assert stale['api_status'] == 'stale' and stale['telemetry'] == {'ethernet_links': []}
    client.put('/api/towers/' + tid, headers=owner, json=settings(api_password='changed-secret'))
    pending = client.get('/api/devices', headers=owner).json()[0]
    assert pending['api_status'] == 'pending' and pending['telemetry'] == {'ethernet_links': []}


def test_inflight_results_dropped_when_tower_credentials_change(client, owner, monkeypatch):
    tid = client.post('/api/towers', headers=owner, json=settings()).json()['id']
    did = device(client, owner, tid)
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=True))
    async def changed(*args, **kwargs):
        response = client.put('/api/towers/' + tid, headers=owner, json=settings(api_password='changed'))
        assert response.status_code == 200
        return {'cpu_percent':1}
    monkeypatch.setattr(worker, 'collect_api', changed)
    asyncio.run(poll(did))
    with SessionLocal() as db:
        assert db.scalar(select(Metric).where(Metric.device_id == did)) is None
        assert db.get(Device, did).last_poll is None
