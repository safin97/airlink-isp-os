import asyncio
from unittest.mock import AsyncMock
import pytest
from airlink import snmp_discovery
from airlink.db import SessionLocal
from airlink.models import SNMPProfile
from monitoring import snmp
from test_api import user


def test_scan_batches_credentials_scope_and_no_automatic_add(client, owner, monkeypatch):
    tid = client.post('/api/towers',headers=owner,json={'name':'North','management_ip':'192.0.2.1'}).json()['id']
    profile = client.post('/api/snmp-profiles',headers=owner,json={'name':'Private','version':'3',
        'username':'reader','auth_key':'private-auth-key','priv_key':'private-priv-key'}).json()['id']
    calls=[]
    async def scan(addresses, profiles):
        calls.append((addresses, profiles))
        return [{'ip_address':addresses[0], 'name':'Radio', 'vendor':'mikrotik', 'vendor_label':'MikroTik',
                 'snmp_version':'3', 'snmp_profile_id':profile, 'profile_name':'Private'}],False
    monkeypatch.setattr(snmp_discovery,'scan_batch',scan)
    path=f'/api/towers/{tid}/discover-snmp'
    response=client.post(path,headers=owner,json={'prefix':24,'offset':0})
    assert response.status_code==200,response.text
    assert response.json()['scanned']==32 and response.json()['next_offset']==32
    assert response.json()['hosts'][0]['already_added'] is False
    assert 'private-auth-key' not in response.text and 'private-priv-key' not in response.text
    assert len(calls[0][0])==32 and calls[0][0][0]=='192.0.2.1'
    assert {p['credentials'].get('version') for p in calls[0][1]}=={'1','2c','3'}
    assert client.get('/api/devices',headers=owner).json()==[]
    response=client.post(path,headers=owner,json={'prefix':24,'offset':224,'profile_id':profile})
    assert response.json()['next_offset'] is None and response.json()['scanned']==254
    assert len(calls[1][1])==1 and calls[1][1][0]['profile_id']==profile
    _,manager=user(client,owner,'manager','discovery-reader')
    assert client.post(path,headers=manager,json={}).status_code==403
    assert client.post(path,headers=owner,json={'prefix':16}).status_code==422
    assert client.post(path,headers=owner,json={'profile_id':'missing'}).status_code==422


def test_public_profile_reuse_is_encrypted_and_matching_version(client, owner):
    path='/api/snmp-profiles/discovery-public'
    first=client.post(path,headers=owner,json={'version':'2c'})
    assert first.status_code==200
    assert 'encrypted_credentials' not in first.text and 'community' not in first.text
    assert client.post(path,headers=owner,json={'version':'2c'}).json()['id']==first.json()['id']
    other=client.post(path,headers=owner,json={'version':'1'}).json()
    assert other['id']!=first.json()['id']
    with SessionLocal() as db:
        assert db.query(SNMPProfile).count()==2
    assert client.post(path,headers=owner,json={'version':'3'}).status_code==422


@pytest.mark.parametrize('oid,vendor', [
    ('1.3.6.1.4.1.14988.1', 'mikrotik'),
    ('1.3.6.1.4.1.43356.1', 'mimosa'),
])
def test_snmp_identity_and_name_without_ping(monkeypatch,oid,vendor):
    monkeypatch.setattr(snmp.UdpTransportTarget,'create',AsyncMock(return_value=object()))
    calls=[]
    async def get(engine,auth,target,context,*oids,**kwargs):
        calls.append(auth.message_processing_model)
        if auth.message_processing_model==0:return 'timeout',0,0,[]
        return (None,0,0,[('oid',oid),('desc','Radio')]) if len(oids)==2 else (None,0,0,[('name','North radio')])
    monkeypatch.setattr(snmp,'get_cmd',get)
    profiles=[{'profile_id':None,'profile_name':'public','credentials':{'version':v,'community':'public'}} for v in ('1','2c')]
    result=asyncio.run(snmp_discovery.identify('192.0.2.1',profiles))
    assert result['vendor']==vendor and result['name']=='North radio'
    assert result['snmp_version']=='2c' and calls==[0,1,1]
    assert 'credentials' not in result


def test_batch_is_bounded_and_returns_only_responders(monkeypatch):
    calls=[]
    async def identify(address, profiles):
        calls.append(address)
        return {'ip_address':address} if address.endswith('.1') else None
    monkeypatch.setattr(snmp_discovery,'identify',identify)
    hosts,limited=asyncio.run(snmp_discovery.scan_batch([f'192.0.2.{i}' for i in range(1,100)],[]))
    assert hosts==[{'ip_address':'192.0.2.1'}] and not limited and len(calls)==32


def test_auto_version_fallback_keeps_private_community_and_reuses_profile(client, owner, monkeypatch):
    source = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'Private v1', 'version': '1', 'community': 'private-discovery-read'}).json()['id']
    with SessionLocal() as db:
        profiles = snmp_discovery.candidates(db)
        fallback = next(p for p in profiles if p.get('source_profile_id') == source)
        assert fallback['credentials'] == {'version': '2c', 'community': 'private-discovery-read'}
        assert len(snmp_discovery.candidates(db, source)) == 1
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    async def get(engine, auth, target, context, *oids, **kwargs):
        if auth.message_processing_model == 0: return 'timeout', 0, 0, []
        return (None, 0, 0, [('oid', '1.3.6.1.4.1.14988.1'), ('desc', 'RouterOS')]) if len(oids) == 2 else (None, 0, 0, [('name', 'Radio')])
    monkeypatch.setattr(snmp, 'get_cmd', get)
    found = asyncio.run(snmp_discovery.identify('192.0.2.1', profiles))
    assert found['vendor'] == 'mikrotik' and found['snmp_version'] == '2c'
    assert found['source_profile_id'] == source and found['snmp_profile_id'] is None
    assert 'private-discovery-read' not in str(found)
    payload = {'source_profile_id': source, 'version': found['snmp_version']}
    path = '/api/snmp-profiles/discovery-match'
    response = client.post(path, headers=owner, json=payload)
    assert response.status_code == 200 and 'private-discovery-read' not in response.text
    profile_id = response.json()['id']
    assert client.post(path, headers=owner, json=payload).json()['id'] == profile_id
    from airlink.security import cipher
    import json
    with SessionLocal() as db:
        credentials = json.loads(cipher().decrypt(db.get(SNMPProfile, profile_id).encrypted_credentials.encode()))
        assert credentials == {'version': '2c', 'community': 'private-discovery-read'}
    _, manager = user(client, owner, 'manager', 'profile-reader')
    assert client.post(path, headers=manager, json=payload).status_code == 403
    v3 = client.post('/api/snmp-profiles', headers=owner, json={'name': 'v3', 'version': '3',
        'username': 'reader', 'auth_key': 'auth-read-key', 'priv_key': 'priv-read-key'}).json()['id']
    assert client.post(path, headers=owner, json={'source_profile_id': v3, 'version': '2c'}).status_code == 422


def test_saved_v3_identity_is_detected_without_community_guessing(monkeypatch):
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    async def get(engine, auth, target, context, *oids, **kwargs):
        return (None, 0, 0, [('oid', '1.3.6.1.4.1.43356.1'), ('desc', 'Mimosa')]) if len(oids) == 2 else (None, 0, 0, [('name', 'Radio')])
    monkeypatch.setattr(snmp, 'get_cmd', get)
    found = asyncio.run(snmp_discovery.identify('192.0.2.1', [{'profile_id': 'v3', 'profile_name': 'v3',
        'credentials': {'version': '3', 'username': 'reader', 'auth_key': 'auth-read-key', 'priv_key': 'priv-read-key'}}]))
    assert found['vendor'] == 'mimosa' and found['snmp_version'] == '3'
    assert found['snmp_profile_id'] == 'v3'


@pytest.mark.parametrize('version,vendor,allowed', [
    ('1', 'ubiquiti', True), ('1', 'ubiquiti_m5', True), ('1', 'ubiquiti_ac', True),
    ('1', 'mikrotik', False), ('1', 'mimosa', False), ('1', 'generic', False),
    ('2', 'mikrotik', True), ('2c', 'mikrotik', True),
    ('2', 'mimosa', True), ('2c', 'mimosa', True),
    ('2c', 'ubiquiti', False), ('2c', 'ubiquiti_m5', False), ('2c', 'ubiquiti_ac', False),
    ('2c', 'generic', False),
    ('3', 'mimosa', True), ('3', 'ubiquiti', True), ('3', 'mikrotik', True),
])
def test_discovery_vendor_version_filter(version, vendor, allowed):
    assert snmp_discovery.discovery_vendor_allowed(vendor, version) is allowed


@pytest.mark.parametrize('oid,versions,expected,calls_expected', [
    ('1.3.6.1.4.1.14988.1', ['1', '2c'], '2c', [0, 1, 1]),
    ('1.3.6.1.4.1.41112.1', ['2c', '1'], '1', [1, 0, 0]),
    ('1.3.6.1.4.1.14988.1', ['1'], None, [0]),
    ('1.3.6.1.4.1.41112.1', ['2c'], None, [1]),
    ('1.3.6.1.4.1.43356.1', ['1', '2c'], '2c', [0, 1, 1]),
    ('1.3.6.1.4.1.43356.1', ['1'], None, [0]),
])
def test_discovery_filters_responses_and_keeps_trying_versions(monkeypatch, oid, versions, expected, calls_expected):
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    calls = []
    async def get(engine, auth, target, context, *oids, **kwargs):
        calls.append(auth.message_processing_model)
        return (None, 0, 0, [('oid', oid), ('desc', 'Radio')]) if len(oids) == 2 else (None, 0, 0, [('name', 'North radio')])
    monkeypatch.setattr(snmp, 'get_cmd', get)
    profiles = [{'profile_id': version, 'profile_name': 'saved',
                 'credentials': {'version': version, 'community': 'private-read'}} for version in versions]
    found = asyncio.run(snmp_discovery.identify('192.0.2.1', profiles))
    assert calls == calls_expected
    if expected is None:
        assert found is None
    else:
        assert found['snmp_version'] == expected
        assert found['snmp_profile_id'] == expected
        assert 'private-read' not in str(found)


def test_apply_discovered_snmp_to_existing_device_preserves_settings(client, owner, monkeypatch):
    from airlink.models import Device, now
    tid = client.post('/api/towers', headers=owner, json={'name':'North', 'management_ip':'192.0.2.1'}).json()['id']
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name':'Discovered v2', 'version':'2', 'community':'private-community'}).json()['id']
    device = client.post('/api/devices', headers=owner, json={
        'tower_id': tid, 'name':'Keep this name', 'ip_address':'192.0.2.1',
        'vendor':'mikrotik', 'model':'Keep model', 'poll_interval':120,
        'retries':4, 'failure_threshold':7, 'cpu_threshold':85, 'enabled':False}).json()
    with SessionLocal() as db:
        obj = db.get(Device, device['id'])
        obj.status = 'offline'; obj.last_poll = now(); obj.failures = 7
        db.commit()
    async def scan(addresses, profiles):
        return [{'ip_address':'192.0.2.1', 'snmp_profile_id':profile, 'snmp_version':'2c',
                 'vendor':'mikrotik', 'name':'Found name', 'profile_name':'Discovered v2'}], False
    monkeypatch.setattr(snmp_discovery, 'scan_batch', scan)
    discovery = client.post('/api/towers/' + tid + '/discover-snmp', headers=owner, json={'prefix':32}).json()['hosts'][0]
    assert discovery['already_added'] and discovery['device_id'] == device['id']
    assert discovery['device_tower_id'] == tid and discovery['assigned_snmp_profile_id'] is None
    assert discovery['snmp_applied'] is False
    route = '/api/devices/' + device['id'] + '/snmp-profile'
    body = {'snmp_profile_id':profile, 'tower_id':tid, 'expected_ip_address':'192.0.2.1', 'previous_snmp_profile_id':None}
    _, manager = user(client, owner, 'manager')
    assert client.put(route, headers=manager, json=body).status_code == 403
    for change in ({'tower_id':'other'}, {'expected_ip_address':'192.0.2.2'}, {'previous_snmp_profile_id':'stale'}):
        assert client.put(route, headers=owner, json={**body, **change}).status_code == 409
    assert client.put(route, headers=owner, json={**body, 'snmp_profile_id':'missing'}).status_code == 404
    result = client.put(route, headers=owner, json=body)
    assert result.status_code == 200, result.text
    assert 'private-community' not in result.text
    with SessionLocal() as db:
        obj = db.get(Device, device['id'])
        assert obj.snmp_profile_id == profile and obj.last_poll is None
        assert obj.status == 'unknown' and obj.failures == 0
        for key in ('name','model','vendor','tower_id','poll_interval','retries','failure_threshold','cpu_threshold','enabled'):
            assert getattr(obj, key) == device[key]
    assert len(client.get('/api/devices', headers=owner).json()) == 1
    assert client.put(route, headers=owner, json=body).status_code == 409
    repeated = client.post('/api/towers/' + tid + '/discover-snmp', headers=owner, json={'prefix':32}).json()['hosts'][0]
    assert repeated['snmp_applied'] is True and repeated['assigned_snmp_profile_id'] == profile
