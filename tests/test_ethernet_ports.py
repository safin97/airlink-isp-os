import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from monitoring import snmp
from test_api import tower, user


@pytest.mark.parametrize('condition', ['connected', 'stale', 'failed', 'disabled', 'pending', 'v1', 'other_vendor'])
def test_ports_states_freshness_and_scope(client, owner, condition):
    uid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=uid)
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'Switch', 'version': '1' if condition == 'v1' else '2c', 'community': 'test-private'}).json()
    did = client.post('/api/devices', headers=owner, json={
        'name': 'Switch', 'ip_address': '192.0.2.4', 'tower_id': tid,
        'vendor': 'mimosa' if condition == 'other_vendor' else 'mikrotik',
        'snmp_profile_id': profile['id']}).json()['id']
    stamp = now() - timedelta(minutes=10 if condition == 'stale' else 0)
    ports = {
        '1': {'name': 'ether1', 'type': 6, 'status': 1, 'admin_status': 1, 'speed_mbps': 1000, 'rx_bps': 24000000, 'tx_bps': 0},
        '2': {'name': 'ether2', 'type': 6, 'status': 2, 'admin_status': 1},
        '3': {'name': 'sfp1', 'type': 6, 'status': 2, 'admin_status': 2},
        '4': {'name': 'renamed-port', 'type': 6},
        '5': {'name': 'bridge', 'type': 209, 'status': 1},
        '6': {'name': 'vlan', 'type': 135, 'status': 1},
    }
    with SessionLocal() as db:
        d = db.get(Device, did)
        d.last_poll = None if condition == 'pending' else stamp
        d.enabled = condition != 'disabled'
        db.add(Metric(device_id=did, collected_at=stamp, values={'snmp_up': condition != 'failed', 'interfaces': ports}))
        db.commit()
    client.put('/api/users/'+uid+'/sections', headers=owner,
               json={'sections': ['towers'], 'editable_sections': []}).raise_for_status()
    result = client.get('/api/devices/'+did+'/ethernet-ports', headers=manager)
    assert result.status_code == 200
    assert 'test-private' not in result.text
    data = result.json()
    if condition in ('v1', 'other_vendor', 'pending'):
        assert data['ports'] == []
    else:
        assert [p['name'] for p in data['ports']] == ['ether1', 'ether2', 'sfp1', 'renamed-port']
        if condition == 'connected':
            assert [p['state'] for p in data['ports']] == ['connected', 'disconnected', 'disabled', 'unknown']
            assert data['ports'][0]['rx_bps'] == 24000000
            assert data['ports'][0]['tx_bps'] == 0
            assert data['ports'][1]['rx_bps'] is None
        else:
            assert all(p['state'] == 'unknown' and p['rx_bps'] is None and p['speed_mbps'] is None for p in data['ports'])
    with SessionLocal() as db:
        db.get(Device, did).tower_id = tower(client, owner, 'Other')
        db.commit()
    assert client.get('/api/devices/'+did+'/ethernet-ports', headers=manager).status_code == 404
    assert client.get('/api/devices/'+did+'/ethernet-ports').status_code == 401


def test_snmp_switch_includes_down_disabled_and_unnamed_ports(monkeypatch):
    tables = {
        snmp.TABLES['if_name']: {'1': 'ether1', '2': 'ether2'},
        snmp.TABLES['if_type']: {'1': 6, '2': 6, '3': 6},
        snmp.TABLES['if_status']: {'1': 1, '2': 2},
        snmp.TABLES['if_admin_status']: {'1': 1, '2': 2},
        snmp.TABLES['if_rx_octets']: {'1': 2**35},
        snmp.TABLES['if_tx_octets']: {'1': 2**36},
    }
    async def read(*args, **kwargs):
        return tables.get(args[3], {})
    monkeypatch.setattr(snmp, 'read_table', read)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=(None, 0, 0, [(snmp.UPTIME, 12300)])))
    values = asyncio.run(snmp.collect('192.0.2.1', {'version': '2c', 'community': 'public'}, 0, vendor='mikrotik'))
    ports = values['interfaces']
    assert set(ports) == {'1', '2', '3'}
    assert ports['2']['admin_status'] == 2 and ports['2']['status'] == 2
    assert ports['3']['name'] == '3'
    assert ports['1']['counter_bits'] == 64
    assert snmp.interface_rate(ports['1'], {**ports['1'], 'rx_octets': 2**35 + 180000000}, 'rx', 60) == 24000000
    assert snmp.interface_rate({}, ports['1'], 'rx', 60) is None
