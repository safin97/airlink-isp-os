import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from monitoring import snmp
from test_api import tower


@pytest.mark.parametrize('total,clients,expected,weakest', [
    ({'0': -627}, {}, -62.7, None),
    ({'0': -510}, {'1': -720}, -51, None),
    ({}, {'1': -650, '2': -725, '3': 0, '4': -2000}, None, -72.5),
    ({'0': 0}, {}, None, None),
    ({'0': -9999}, {'1': 0}, None, None),
])
def test_mimosa_signal_scaling_missing_values_and_total_priority(monkeypatch, total, clients, expected, weakest):
    requested = []
    async def table(engine, auth, target, oid, textual=False):
        requested.append(oid)
        return {snmp.MIMOSA_TOTAL_RX: total, snmp.MIMOSA_CLIENT_RSSI: clients}.get(oid, {})
    monkeypatch.setattr(snmp, 'read_table', table)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=(None, 0, 0, [(snmp.UPTIME, 12300)])))
    result = asyncio.run(snmp.collect('192.0.2.1', {'version': '2c', 'community': 'test'}, 0, vendor='mimosa'))
    assert result.get('signal_dbm') == expected
    assert result.get('weakest_signal_dbm') == weakest
    assert 'wireless_clients' not in result
    if expected is not None:
        assert snmp.MIMOSA_CLIENT_RSSI not in requested


@pytest.mark.parametrize('ports,expected', [
    ({'1': {'name': 'ether1', 'type': 6, 'status': 1, 'speed_mbps': 1000, 'tx_bps': 24000000, 'rx_bps': 0},
      '2': {'name': 'br0', 'type': 209, 'status': 1, 'tx_bps': 999999999}},
     {'name': 'ether1', 'speed_mbps': 1000, 'tx_bps': 24000000, 'rx_bps': 0}),
    ({'1': {'name': 'eth0', 'type': 6, 'status': 1, 'speed_mbps': 100}},
     {'name': 'eth0', 'speed_mbps': 100}),
    ({'1': {'name': 'eth0', 'type': 6, 'status': 1}, '2': {'name': 'eth1', 'type': 6, 'status': 1}}, None),
    ({'1': {'name': 'ether1', 'type': 6, 'status': 2, 'speed_mbps': 1000, 'tx_bps': 500}}, None),
])
def test_mimosa_inventory_ethernet_selection_and_stale_removal(client, owner, ports, expected):
    tid = tower(client, owner)
    response = client.post('/api/devices', headers=owner, json={
        'name': 'Mimosa link', 'ip_address': '192.0.2.9', 'tower_id': tid, 'vendor': 'mimosa'})
    assert response.status_code == 201
    did = response.json()['id']
    with SessionLocal() as db:
        device = db.get(Device, did)
        device.last_poll = now()
        metric = Metric(device_id=did, values={'snmp_up': True, 'signal_dbm': -62.7, 'interfaces': ports})
        db.add(metric)
        db.commit()
        metric_id = metric.id
    reading = client.get('/api/devices', headers=owner).json()[0]['telemetry']
    assert reading['signal_dbm'] == -62.7
    assert reading.get('ethernet_traffic') == expected
    with SessionLocal() as db:
        db.get(Metric, metric_id).collected_at = now() - timedelta(minutes=20)
        db.commit()
    stale = client.get('/api/devices', headers=owner).json()[0]['telemetry']
    assert 'ethernet_traffic' not in stale and 'signal_dbm' not in stale
