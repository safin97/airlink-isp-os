import asyncio
from unittest.mock import AsyncMock
import fakeredis
import pytest
from airlink.vendor_identity import identify_vendor, merge_vendor
from airlink.device_api import airos_values
from monitoring import worker, snmp
from test_api import device
from test_tower_api import settings


async def poll(device_id):
    await worker.poll(device_id, asyncio.Semaphore(1))


@pytest.mark.parametrize('oid,description,expected', [
    ('1.3.6.1.4.1.14988.1','RouterOS','mikrotik'),
    ('1.3.6.1.4.1.149880.1','','generic'),
    ('1.3.6.1.4.1.41112.1','NanoStation M5','ubiquiti_m5'),
    ('1.3.6.1.4.1.10002','NSM5','ubiquiti_m5'),
    ('1.3.6.1.4.1.41112.1','LBE-5AC-Gen2','ubiquiti_ac'),
    ('1.3.6.1.4.1.41112.1','airMAX AC','ubiquiti_ac'),
    ('1.3.6.1.4.1.41112.1','Linux','ubiquiti'),
    ('','MikroTik RouterOS 7','mikrotik'),
    ('','Mimosa B5','mimosa'),
    ('1.3.6.1.4.1.43356.2','','mimosa'),
    ('1.3.6.1.4.1.433560.2','','generic'),
    ('','generic Linux bridge','generic'),
    ('','unknown AC powered device','generic'),
])
def test_vendor_identity_uses_confirmed_identity(oid, description, expected):
    assert identify_vendor(oid, description) == expected


def test_snmp_description_selects_ubiquiti_adapter(monkeypatch):
    monkeypatch.setattr(snmp.UdpTransportTarget,'create',AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp,'get_cmd',AsyncMock(side_effect=[
        (None,0,0,[(snmp.UPTIME,100)]),
        (None,0,0,[('oid','1.3.6.1.4.1.41112.1'),('descr','NanoStation M5')])]))
    tables=AsyncMock(return_value={});monkeypatch.setattr(snmp,'read_table',tables)
    result=asyncio.run(snmp.collect('192.0.2.2',{'version':'2c','community':'test'},0,vendor='auto'))
    assert result['detected_vendor']=='ubiquiti_m5'
    assert set(snmp.WIRELESS_TABLES['ubiquiti'].values()).issubset({c.args[3] for c in tables.call_args_list})
    assert airos_values({'wireless':{},'host':{'devmodel':'NBE-5AC-Gen2'}})['detected_vendor']=='ubiquiti_ac'
    assert merge_vendor('ubiquiti_m5','ubiquiti')=='ubiquiti_m5'


def test_automatic_vendor_display_failure_retention_and_manual_override(client, owner, monkeypatch):
    tid=client.post('/api/towers', headers=owner, json=settings()).json()['id']
    did=device(client,owner,tid)
    monkeypatch.setattr(worker,'cache',fakeredis.FakeRedis())
    monkeypatch.setattr(worker,'ping',AsyncMock(return_value=True))
    probe=AsyncMock(return_value={'detected_vendor':'mikrotik','vendor_detection_source':'API'})
    monkeypatch.setattr(worker,'collect_api',probe)
    asyncio.run(poll(did))
    result=client.get('/api/devices',headers=owner).json()[0]
    assert result['vendor']=='generic' and result['vendor_auto'] is True
    assert result['detected_vendor']=='mikrotik' and result['vendor_label']=='MikroTik'
    probe.side_effect=RuntimeError('unreachable')
    asyncio.run(poll(did))
    assert client.get('/api/devices',headers=owner).json()[0]['vendor_label']=='MikroTik'
    # Moving to another address clears the identity until that device responds.
    data={'name':'Router','ip_address':'192.0.2.3','tower_id':tid}
    assert client.put('/api/devices/'+did,headers=owner,json=data).status_code==200
    result=client.get('/api/devices',headers=owner).json()[0]
    assert result['detected_vendor'] is None
    asyncio.run(poll(did))
    assert client.get('/api/devices',headers=owner).json()[0]['detected_vendor'] is None
    data['vendor']='ubiquiti_m5'
    assert client.put('/api/devices/'+did,headers=owner,json=data).status_code==200
    result=client.get('/api/devices',headers=owner).json()[0]
    assert result['vendor_auto'] is False and result['vendor_label']=='Ubiquiti airMAX M5'


@pytest.mark.parametrize('oid,description,expected', [
    ('1.3.6.1.4.1.59646.1', '', 'tenda'),
    ('.1.3.6.1.4.1.11863.1', 'Linux', 'tplink'),
    ('1.3.6.1.4.1.65855', '', 'tplink'),
    ('1.3.6.1.4.1.4881.1', '', 'ruijie'),
    ('1.3.6.1.4.1.39165.1', '', 'hikvision'),
    ('', '<title>Tenda Wireless Router</title>', 'tenda'),
    ('', '<img src="Tenda_logo.png">', 'tenda'),
    ('', '<title>TP-Link Router</title>', 'tplink'),
    ('', '<title>TP LINK Archer</title>', 'tplink'),
    ('', 'Visit tplinkwifi.net', 'tplink'),
    ('', 'http://tplinklogin.net/', 'tplink'),
    ('', '<title>Ruijie Networks</title>', 'ruijie'),
    ('', '<title>Reyee Router</title>', 'ruijie'),
    ('', 'HIKVISION Device', 'hikvision'),
    ('', '<img src="hikvision_logo.png">', 'hikvision'),
    ('', 'AC1200 WiFi Router', 'generic'),
    ('', 'attendance router tplinked hikvisionary', 'generic'),
    ('1.3.6.1.4.1.48810.1', '', 'generic'),
    ('1.3.6.1.4.1.391650.1', '', 'generic'),
    ('1.3.6.1.4.1.118630.1', '', 'generic'),
    ('1.3.6.1.4.1.596460.1', '', 'generic'),
    ('1.3.6.1.4.1.14988.1', 'Tenda subscriber router', 'mikrotik'),
])
def test_additional_router_brand_identity(oid, description, expected):
    assert identify_vendor(oid, description) == expected


@pytest.mark.parametrize('oid,vendor', [('59646','tenda'), ('11863','tplink'), ('65855','tplink'),
                                       ('4881','ruijie'), ('39165','hikvision')])
def test_new_brands_use_standard_snmp_tables_without_guessing_radio_oids(monkeypatch, oid, vendor):
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(side_effect=[
        (None,0,0,[(snmp.UPTIME,100)]),
        (None,0,0,[('oid','1.3.6.1.4.1.' + oid), ('descr','Device')])]))
    tables = AsyncMock(return_value={})
    monkeypatch.setattr(snmp, 'read_table', tables)
    result = asyncio.run(snmp.collect('192.168.1.2', {'version':'2c', 'community':'test'}, 0, vendor='auto', link_only=True))
    assert result['detected_vendor'] == vendor
    called = {call.args[3] for call in tables.call_args_list}
    assert snmp.TABLES['if_speed_mbps'] in called
    assert not called.intersection(oid for fields in snmp.WIRELESS_TABLES.values() for oid in fields.values())
