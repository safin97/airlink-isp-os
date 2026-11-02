import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from monitoring import snmp
from test_api import user, tower, device


def test_connected_clients_scope_freshness_and_secret_filter(client, owner):
    manager_id, manager = user(client, owner, 'manager', 'wireless-manager')
    tid = tower(client, owner, 'Allowed', manager=manager_id)
    did = device(client, owner, tid)
    other = device(client, owner, tower(client, owner, 'Other'), '192.0.2.2')
    client.put('/api/users/'+manager_id+'/sections', headers=owner,
               json={'sections':['towers'], 'editable_sections':[]}).raise_for_status()
    with SessionLocal() as db:
        d = db.get(Device, did); d.last_poll = now()
        metric = Metric(device_id=did, values={'wireless_clients':1, 'wireless_registration_source':'SNMP',
            'wireless_registrations':[{'mac_address':'aa:bb:cc:dd:ee:01','interface':'wlan1',
                                     'ssid':'North','signal_dbm':-60,'password':'secret-must-not-leak'}]})
        db.add(metric); db.commit()
        path = '/api/devices/'+did+'/wireless-clients'
        response = client.get(path, headers=manager)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'available' and data['total'] == 1
        assert data['clients'][0]['mac_address'] == 'AA:BB:CC:DD:EE:01'
        assert 'secret-must-not-leak' not in response.text
        assert client.get('/api/devices/'+other+'/wireless-clients', headers=manager).status_code == 404
        metric.collected_at = now()-timedelta(hours=1); db.commit()
        assert client.get(path, headers=manager).json()['status'] == 'stale'
        assert client.get(path, headers=manager).json()['clients'] == []
    client.put('/api/users/'+manager_id+'/sections', headers=owner,
               json={'sections':['isp_card']}).raise_for_status()
    assert client.get(path, headers=manager).status_code == 403


@pytest.mark.parametrize('vendor,index,ssid_oid,signal_oid', [
    ('mikrotik','170.187.204.221.238.1.3','1.3.6.1.4.1.14988.1.1.1.3.1.4','1.3.6.1.4.1.14988.1.1.1.2.1.3'),
    ('ubiquiti','3.170.187.204.221.238.1','1.3.6.1.4.1.41112.1.4.5.1.2','1.3.6.1.4.1.41112.1.4.7.1.3'),
])
def test_snmp_registration_index_maps_mac_interface_and_ssid(monkeypatch, vendor, index, ssid_oid, signal_oid):
    async def table(engine, auth, target, oid, textual=False):
        if oid == snmp.TABLES['if_name']: return {'3':'wlan1'}
        if oid == ssid_oid: return {'3':'North'}
        if oid == signal_oid: return {index:-60, 'bad-index':-70}
        return {}
    monkeypatch.setattr(snmp,'read_table',table)
    monkeypatch.setattr(snmp.UdpTransportTarget,'create',AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp,'get_cmd',AsyncMock(return_value=(None,0,0,[(snmp.UPTIME,100)])))
    values = asyncio.run(snmp.collect('192.0.2.1', {'version':'2c','community':'public'}, 0, vendor=vendor))
    assert values['wireless_ssids'] == ['North']
    assert values['wireless_registrations'] == [{'mac_address':'AA:BB:CC:DD:EE:01', 'interface':'wlan1', 'ssid':'North', 'signal_dbm':-60}]
    assert values['wireless_clients'] == 1
