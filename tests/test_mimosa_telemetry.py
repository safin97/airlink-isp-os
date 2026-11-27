import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from airlink import device_telemetry
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
def test_mimosa_inventory_ethernet_selection_and_last_known_readings(client, owner, ports, expected):
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
    assert (reading.get('ethernet_traffic') or None) == expected
    with SessionLocal() as db:
        db.get(Metric, metric_id).collected_at = now() - timedelta(minutes=20)
        db.commit()
    stale = client.get('/api/devices', headers=owner).json()[0]
    assert stale['telemetry'] == reading
    expected_stale = set(reading)
    if not reading['ethernet_links']:
        expected_stale.remove('ethernet_links')  # No speed was ever observed.
        assert 'ethernet_links' not in stale['telemetry_field_times']
    assert set(stale['telemetry_stale_fields']) == expected_stale


@pytest.mark.parametrize('high,legacy,expected', [
    (None, 1_000_000_000, 1000), (0, 100_000_000, 100),
    (None, 10_000_000, 10), (1000, 100_000_000, 1000),
    (None, 0, None), (None, 2**32 - 1, None),
])
@pytest.mark.parametrize('vendor', ['mimosa', 'auto'])
def test_c5c_standard_ethernet_speed_without_traffic_counters(monkeypatch, high, legacy, expected, vendor):
    tables = {
        snmp.FALLBACK_TABLES['if_descr']: {'1': 'eth0', '2': 'wlan0', '3': 'br0'},
        snmp.TABLES['if_type']: {'1': 6, '2': 71, '3': 209},
        snmp.TABLES['if_status']: {'1': 1, '2': 1, '3': 1},
        snmp.TABLES['if_speed_mbps']: {'2': 866, '3': 1000},
        snmp.FALLBACK_TABLES['if_speed']: {'1': legacy},
    }
    if high is not None:
        tables[snmp.TABLES['if_speed_mbps']]['1'] = high
    async def read(*args, **kwargs):
        return tables.get(args[3], {})
    replies = [(None, 0, 0, [(snmp.UPTIME, 12300)])]
    if vendor == 'auto':
        replies.append((None, 0, 0, [('sysObjectID', '1.3.6.1.4.1.43356.1.1.7'), ('sysDescr', 'Mimosa C5c')]))
    monkeypatch.setattr(snmp, 'read_table', read)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(side_effect=replies))
    values = asyncio.run(snmp.collect('192.0.2.5', {'version': '2c', 'community': 'test'}, 0, vendor=vendor))
    readings = device_telemetry.readings(values, values.get('detected_vendor', vendor))
    assert readings.get('ethernet_links', []) == (
        [{'name': 'eth0', 'speed_mbps': expected}] if expected else [])
    assert 'rx_bps' not in readings['ethernet_traffic']
    assert 'tx_bps' not in readings['ethernet_traffic']


def test_c5c_speed_keeps_its_own_timestamp_when_traffic_poll_is_partial(client, owner):
    tid = tower(client, owner)
    did = client.post('/api/devices', headers=owner, json={
        'name': 'C5c', 'model': 'C5c', 'vendor': 'mimosa',
        'ip_address': '192.0.2.5', 'tower_id': tid}).json()['id']
    stamp = now() - timedelta(seconds=30)
    link = {'1': {'name': 'eth0', 'type': 6, 'status': 1, 'speed_mbps': 1000}}
    def save(values, at):
        with SessionLocal() as db:
            device = db.get(Device, did)
            device.last_poll = at
            device_telemetry.remember(db, device, values, at)
            db.add(Metric(device_id=did, collected_at=at, values=values))
            db.commit()
        return client.get('/api/devices', headers=owner).json()[0]

    original = save({'snmp_up': True, 'interfaces': link}, stamp)
    for offset, values in enumerate([
        {'snmp_up': True, 'interfaces': {}},
        {'snmp_up': True, 'interfaces': {'1': {**link['1'], 'status': 2}}},
        {'snmp_up': True, 'interfaces': {'1': {**link['1'], 'admin_status': 2}}},
        {'snmp_up': False, 'interfaces': {}},
    ], 1):
        row = save(values, stamp + timedelta(seconds=offset))
        assert row['telemetry']['ethernet_links'] == [{'name': 'eth0', 'speed_mbps': 1000}]
        assert row['telemetry_field_times']['ethernet_links'] == original['telemetry_field_times']['ethernet_links']
        assert 'ethernet_links' in row['telemetry_stale_fields']
    recovered = save({'snmp_up': True, 'interfaces': {'1': {**link['1'], 'speed_mbps': 100}}}, now())
    assert recovered['telemetry']['ethernet_links'] == [{'name': 'eth0', 'speed_mbps': 100}]
    assert recovered['telemetry_field_times']['ethernet_links'] != original['telemetry_field_times']['ethernet_links']
