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


@pytest.mark.parametrize('oid,vendor', [('1.3.6.1.4.1.14988.1','mikrotik'),
    ('1.3.6.1.4.1.41112.1','ubiquiti'),('1.3.6.1.4.1.43356.1','mimosa')])
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
