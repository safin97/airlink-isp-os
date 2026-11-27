import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import fakeredis
import httpx
import pytest

from airlink import api, device_api
from airlink.models import now
from monitoring import worker
from test_tower_api import settings


@pytest.mark.parametrize('status,body,expected', [
    (200, [{'.id': '*1'}, {'.id': '*2'}], 2),
    (200, [], 0),
    (403, {}, None),
    (500, {}, None),
    (200, {'error': 'unavailable'}, None),
    (200, [{'.id': '*1'}, {}], None),
])
def test_ccr_reads_only_active_session_ids(status, body, expected):
    def transport(request):
        path = request.url.path
        if path == '/':
            return httpx.Response(200, text='RouterOS')
        if path == '/rest/interface/ethernet':
            return httpx.Response(200, json=[
                {'.id': '*1', 'name': 'ether1', 'running': 'true', 'disabled': 'false'},
                {'.id': '*2', 'name': 'ether2', 'running': 'false'},
                {'.id': '*3', 'name': 'sfp1', 'running': True, 'disabled': True},
                {'.id': '*4', 'name': 'ether4'}])
        if path == '/rest/interface/ethernet/monitor':
            return httpx.Response(200, json=[])
        if path == '/rest/ppp/active':
            assert request.method == 'GET'
            assert request.url.params['.proplist'] == '.id'
            return httpx.Response(status, json=body)
        if path == '/rest/system/resource':
            return httpx.Response(200, json={'cpu-load': '12', 'board-name': 'CCR2004'})
        raise AssertionError(path)

    values = asyncio.run(device_api.collect_api('192.0.2.1', {
        'api_username': 'monitor', 'api_password': 'test'}, vendor='mikrotik_ccr',
        inventory=True, transport=httpx.MockTransport(transport)))
    assert values.get('ppp_active_count') == expected
    assert ('ppp_active_count' in values) == (expected is not None)
    assert values['cpu_percent'] == 12
    assert 'wireless_clients' not in values
    assert values['ethernet_port_counts'] == {'online': 1, 'offline': 2, 'unknown': 1}


def test_ccr_vendor_polling_retains_count_and_recovers_to_zero(client, owner, monkeypatch):
    tid = client.post('/api/towers', headers=owner, json=settings()).json()['id']
    response = client.post('/api/devices', headers=owner, json={
        'tower_id': tid, 'name': 'Core router', 'ip_address': '192.0.2.1', 'vendor': 'mikrotik_ccr'})
    assert response.status_code == 201, response.text
    did = response.json()['id']
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    monkeypatch.setattr(worker, 'ping', AsyncMock(return_value=False))
    probe = AsyncMock(return_value={'ppp_active_count': 350, 'detected_vendor': 'mikrotik'})
    monkeypatch.setattr(worker, 'collect_api', probe)
    clock = now()
    monkeypatch.setattr(worker, 'now', lambda: clock)
    monkeypatch.setattr(api, 'now', lambda: clock)

    def poll():
        async def run():
            await worker.poll(did, asyncio.Semaphore(1))
        asyncio.run(run())
        return client.get('/api/devices', headers=owner).json()[0]

    first = poll()
    assert probe.call_args.kwargs['vendor'] == 'mikrotik_ccr'
    assert first['vendor_label'] == 'MikroTik CCR'
    assert first['telemetry']['ppp_active_count'] == 350
    stamp = first['telemetry_field_times']['ppp_active_count']
    probe.side_effect = RuntimeError('unreachable')
    for _ in range(3):
        clock += timedelta(minutes=1)
        down = poll()
    assert down['status'] == 'offline'
    assert down['telemetry']['ppp_active_count'] == 350
    assert 'ppp_active_count' in down['telemetry_stale_fields']
    assert down['telemetry_field_times']['ppp_active_count'] == stamp
    probe.side_effect = None
    probe.return_value = {'cpu_percent': 15}  # PPP read denied, other reads succeed.
    clock += timedelta(minutes=1)
    partial = poll()
    assert partial['status'] == 'online'
    assert partial['telemetry']['ppp_active_count'] == 350
    assert 'ppp_active_count' in partial['telemetry_stale_fields']
    probe.return_value = {'ppp_active_count': 0}
    clock += timedelta(minutes=1)
    recovered = poll()
    assert recovered['telemetry']['ppp_active_count'] == 0
    assert 'ppp_active_count' not in recovered['telemetry_stale_fields']
