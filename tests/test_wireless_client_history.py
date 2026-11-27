import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import pytest
from sqlalchemy import delete

from airlink import api
from airlink.db import SessionLocal
from airlink.models import Metric, now
from monitoring import worker, snmp
from test_api import tower


def test_client_status_history_keeps_order_across_disconnects_failures_and_recovery(client, owner, monkeypatch):
    tid = tower(client, owner)
    profile = client.post('/api/snmp-profiles/discovery-public', headers=owner,
                          json={'version': '2c'}).json()['id']
    did = client.post('/api/devices', headers=owner, json={
        'name': 'AP', 'ip_address': '192.0.2.1', 'tower_id': tid,
        'vendor': 'mikrotik', 'snmp_profile_id': profile}).json()['id']
    clock = now()
    monkeypatch.setattr(worker, 'now', lambda: clock)
    monkeypatch.setattr(api, 'now', lambda: clock)
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=False))
    probe = AsyncMock()
    monkeypatch.setattr(worker, 'collect', probe)
    path = f'/api/devices/{did}/wireless-clients'

    def readings(macs, complete=True):
        return {'snmp_up': True, 'wireless_clients': len(macs),
                'wireless_registration_source': 'SNMP', 'wireless_registrations_complete': complete,
                'wireless_registrations': [{'mac_address': mac, 'ssid': 'North', 'signal_dbm': -65}
                                           for mac in macs]}

    def poll(values):
        nonlocal clock
        clock += timedelta(seconds=60)
        probe.side_effect = values if isinstance(values, Exception) else None
        probe.return_value = values
        async def run():
            await worker.poll(did, asyncio.Semaphore(1))
        asyncio.run(run())
        result = client.get(path, headers=owner).json()
        rows = result['clients']
        assert result['counts'] == {
            'online': sum(row['status'] == 'up' for row in rows),
            'offline': sum(row['status'] == 'down' for row in rows),
            'unknown': sum(row['status'] == 'unknown' for row in rows),
            'limited': False,
        }
        inventory = client.get('/api/devices', headers=owner).json()[0]
        assert inventory['registration_counts'] == result['counts']
        return rows

    a, b, c = ['AA:BB:CC:DD:EE:0' + n for n in ('1', '2', '3')]
    first = poll(readings([b, a]))
    assert [r['mac_address'] for r in first] == [a, b]
    assert [r['status'] for r in first] == ['up', 'up']
    down = poll(readings([b]))
    assert [r['mac_address'] for r in down] == [a, b]
    assert [r['status'] for r in down] == ['down', 'up']
    assert down[0]['last_seen'] == first[0]['last_seen']
    assert down[0]['signal_dbm'] == -65
    recovered = poll(readings([c, b, a]))
    assert [r['mac_address'] for r in recovered] == [a, b, c]
    assert all(r['status'] == 'up' for r in recovered)
    partial = poll(readings([b], complete=False))
    assert [r['status'] for r in partial] == ['unknown', 'up', 'unknown']
    assert partial[0]['last_status'] == 'up'
    failed = poll(RuntimeError('Timeout'))
    assert all(r['status'] == 'unknown' for r in failed)
    empty = poll(readings([]))
    assert [r['mac_address'] for r in empty] == [a, b, c]
    assert all(r['status'] == 'down' for r in empty)
    assert client.get(path, headers=owner).json()['total'] == 0
    poll(readings([b, a]))
    # Display history is separate from raw metrics and the dashboard telemetry.
    telemetry = client.get('/api/devices', headers=owner).json()[0]['telemetry']
    assert '_registration_history' not in telemetry
    with SessionLocal() as db:
        db.execute(delete(Metric).where(Metric.device_id == did))
        db.commit()
    retained = client.get(path, headers=owner).json()['clients']
    assert [r['mac_address'] for r in retained] == [a, b, c]
    assert all(r['status'] == 'unknown' for r in retained)
    # Address edits retain history without attributing it to another address.
    client.put(f'/api/devices/{did}', headers=owner, json={
        'name': 'AP', 'tower_id': tid, 'ip_address': '192.0.2.2',
        'vendor': 'mikrotik', 'snmp_profile_id': profile}).raise_for_status()
    assert all(r['status'] == 'unknown' for r in poll(readings([])))


def test_partial_snmp_walk_cannot_confirm_missing_clients(monkeypatch):
    async def walk(*args, **kwargs):
        yield None, 0, 0, [('1.2.3.1', -65)]
        yield 'timeout', 0, 0, []
    monkeypatch.setattr(snmp, 'walk_cmd', walk)
    rows = asyncio.run(snmp.read_table(None, None, None, '1.2.3'))
    assert rows == {'1': -65}
    assert rows.complete is False


@pytest.mark.parametrize('vendor', ['mikrotik', 'ubiquiti'])
@pytest.mark.parametrize('partial,empty', [(False, False), (True, False), (False, True)])
def test_snmp_registration_completeness(vendor, partial, empty, monkeypatch):
    async def table(engine, auth, target, oid, textual=False):
        rows = snmp.TableRows()
        rows.complete = not partial
        if oid == snmp.WIRELESS_TABLES[vendor]['client_count']:
            rows['1'] = 0 if empty else 1
        registration_oid = (snmp.WIRELESS_TABLES[vendor]['signal_dbm'] if vendor == 'mikrotik'
                            else '1.3.6.1.4.1.41112.1.4.7.1.3')
        if oid == registration_oid and not empty:
            rows['170.187.204.221.238.1.1' if vendor == 'mikrotik' else '1.170.187.204.221.238.1'] = -65
        return rows
    monkeypatch.setattr(snmp, 'read_table', table)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=(None, 0, 0, [(snmp.UPTIME, 100)])))
    values = asyncio.run(snmp.collect('192.0.2.1', {'version': '2c', 'community': 'test'}, 0, vendor=vendor))
    assert values['wireless_registrations_complete'] is not partial
    assert len(values['wireless_registrations']) == (0 if empty else 1)


def test_truncated_api_list_does_not_confirm_disconnections():
    from airlink.device_api import airos_values
    values = airos_values({'wireless': {}, 'sta': [
        {'mac': f'AA:BB:CC:DD:{n // 256:02X}:{n % 256:02X}', 'signal': -65}
        for n in range(257)]}, inventory=True)
    assert len(values['wireless_registrations']) == 256
    assert values['wireless_registrations_complete'] is False


@pytest.mark.parametrize('wifi_status', [200, 500])
@pytest.mark.parametrize('truncated', [False, True])
def test_routeros_collects_all_radio_families_before_confirming_disconnections(wifi_status, truncated):
    import httpx
    from airlink.device_api import collect_api
    def transport(request):
        path = request.url.path
        if path == '/': return httpx.Response(200, text='RouterOS')
        if path == '/rest/interface/ethernet': return httpx.Response(200, json=[])
        if path == '/rest/interface/wireless/registration-table':
            return httpx.Response(200, json=[
                {'mac-address': f'AA:BB:CC:DD:{n // 256:02X}:{n % 256:02X}', 'signal-strength': '-65'}
                for n in range(257)] if truncated else [{'mac-address': 'AA:BB:CC:DD:EE:01', 'signal-strength': '-65'}])
        if path == '/rest/interface/wifi/registration-table':
            return httpx.Response(wifi_status, json=[{'mac-address': 'AA:BB:CC:DD:EE:02', 'signal': -66}])
        return httpx.Response(404)
    values = asyncio.run(collect_api('192.0.2.1', {'api_username': 'test', 'api_password': 'test'},
                                    vendor='mikrotik', inventory=True, transport=httpx.MockTransport(transport)))
    assert values['wireless_clients'] == ((258 if wifi_status == 200 else 257) if truncated else (2 if wifi_status == 200 else 1))
    assert values['wireless_registrations_complete'] is (wifi_status == 200 and not truncated)
