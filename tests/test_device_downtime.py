import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from sqlalchemy import select, delete

import fakeredis
import pytest

from airlink import api
from airlink.db import SessionLocal
from airlink.models import Device, DeviceOutage, Metric, now
from airlink.security import aware
from monitoring import worker
from test_api import device, tower, user


@pytest.mark.parametrize('status,enabled,age,has_start,expected', [
    ('offline', True, 0, True, 7200),
    ('offline', True, 600, True, None),
    ('offline', False, 0, True, None),
    ('offline', True, 0, False, None),
    ('online', True, 0, True, None),
    ('unknown', True, 0, True, None),
])
def test_downtime_only_for_confirmed_fresh_outage(client, owner, monkeypatch,
        status, enabled, age, has_start, expected):
    did = device(client, owner, tower(client, owner))
    clock = now()
    monkeypatch.setattr(api, 'now', lambda: clock)
    with SessionLocal() as db:
        row = db.get(Device, did)
        row.status, row.enabled = status, enabled
        row.last_poll = clock - timedelta(seconds=age)
        row.down_since = clock - timedelta(hours=2) if has_start else None
        # Last success is not an accurate outage start, especially for a new device.
        row.last_success = clock - timedelta(days=30)
        db.commit()
    result = client.get('/api/devices', headers=owner).json()[0]
    assert result['downtime_seconds'] == expected
    if expected is not None:
        monkeypatch.setattr(api, 'now', lambda: clock + timedelta(seconds=60))
        assert client.get('/api/devices', headers=owner).json()[0]['downtime_seconds'] == 7260


@pytest.mark.parametrize('recovery', ['ping', 'snmp', 'api'])
def test_outage_survives_polls_and_clears_on_recovery(client, owner, monkeypatch, recovery):
    tid = client.post('/api/towers', headers=owner, json={
        'name': 'North', 'api_enabled': True, 'api_username': 'monitor', 'api_password': 'test-secret'}).json()['id']
    profile = client.post('/api/snmp-profiles/discovery-public', headers=owner, json={'version': '2c'}).json()['id']
    data = {'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.1', 'snmp_profile_id': profile}
    did = client.post('/api/devices', headers=owner, json=data).json()['id']
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    ping = AsyncMock(return_value=False)
    snmp = AsyncMock(side_effect=RuntimeError('unreachable'))
    probe = AsyncMock(side_effect=RuntimeError('unreachable'))
    monkeypatch.setattr(worker, 'ping', ping)
    monkeypatch.setattr(worker, 'collect', snmp)
    monkeypatch.setattr(worker, 'collect_api', probe)
    clock = now()
    monkeypatch.setattr(worker, 'now', lambda: clock)
    monkeypatch.setattr(api, 'now', lambda: clock)
    async def poll():
        await worker.poll(did, asyncio.Semaphore(1))
    start = clock
    for index in range(3):
        clock = start + timedelta(minutes=index)
        asyncio.run(poll())
        with SessionLocal() as db:
            row = db.get(Device, did)
            assert aware(row.down_since) == start
            assert row.status == ('offline' if index == 2 else 'unknown')
    clock = start + timedelta(hours=2)
    asyncio.run(poll())
    assert client.get('/api/devices', headers=owner).json()[0]['downtime_seconds'] == 7200
    if recovery == 'ping':
        ping.return_value = True
    elif recovery == 'snmp':
        snmp.side_effect, snmp.return_value = None, {'snmp_up': True}
    else:
        probe.side_effect, probe.return_value = None, {}
    clock += timedelta(minutes=1)
    asyncio.run(poll())
    with SessionLocal() as db:
        row = db.get(Device, did)
        assert row.down_since is None and row.status == 'online' and row.failures == 0
        outage = db.scalar(select(DeviceOutage).where(DeviceOutage.device_id == did))
        assert aware(outage.started_at) == start and aware(outage.ended_at) == clock
    history = client.get('/api/devices/' + did + '/outages', headers=owner).json()
    assert len(history) == 1 and history[0]['duration_seconds'] == 7260
    # Further successful polls must not duplicate the completed event.
    asyncio.run(poll())
    assert client.get('/api/devices/' + did + '/outages', headers=owner).json() == history
    ping.return_value = False
    snmp.side_effect = probe.side_effect = RuntimeError('unreachable')
    clock += timedelta(minutes=1)
    asyncio.run(poll())
    with SessionLocal() as db:
        assert aware(db.get(Device, did).down_since) == clock
    # A changed management address must not inherit the old address's outage.
    assert client.put('/api/devices/' + did, headers=owner,
        json={**data, 'ip_address': '192.0.2.2'}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Device, did).down_since is None
        # Telemetry retention and configuration changes do not erase history.
        db.execute(delete(Metric).where(Metric.device_id == did))
        db.commit()
    assert client.get('/api/devices/' + did + '/outages', headers=owner).json() == history


def test_brief_failure_below_threshold_does_not_record_outage(client, owner, monkeypatch):
    did = device(client, owner, tower(client, owner))
    monkeypatch.setattr(worker, 'cache', fakeredis.FakeRedis())
    ping = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, 'ping', ping)
    async def poll():
        await worker.poll(did, asyncio.Semaphore(1))
    asyncio.run(poll())
    ping.return_value = True
    asyncio.run(poll())
    assert client.get('/api/devices/' + did + '/outages', headers=owner).json() == []
    with SessionLocal() as db:
        assert db.get(Device, did).down_since is None


def test_outage_history_scope_permissions_and_order(client, owner):
    mid, manager = user(client, owner, 'manager')
    did = device(client, owner, tower(client, owner, manager=mid))
    outside = device(client, owner, tower(client, owner, name='Other'), ip='192.0.2.2')
    stamp = now()
    with SessionLocal() as db:
        db.add_all([
            DeviceOutage(device_id=did, started_at=stamp-timedelta(days=40, hours=2), ended_at=stamp-timedelta(days=40)),
            DeviceOutage(device_id=did, started_at=stamp-timedelta(hours=1), ended_at=stamp),
        ])
        db.commit()
    endpoint = '/api/devices/' + did + '/outages'
    assert client.get(endpoint).status_code == 401
    client.put('/api/users/'+mid+'/sections', headers=owner,
        json={'sections': ['monitoring'], 'editable_sections': [], 'deletable_sections': []}).raise_for_status()
    response = client.get(endpoint, headers=manager)
    assert response.status_code == 200
    assert [row['duration_seconds'] for row in response.json()] == [3600, 7200]
    assert len(client.get(endpoint+'?limit=1', headers=manager).json()) == 1
    assert client.get(endpoint+'?limit=501', headers=manager).status_code == 422
    assert client.get('/api/devices/'+outside+'/outages', headers=manager).status_code == 404
    client.put('/api/users/'+mid+'/sections', headers=owner,
        json={'sections': ['towers'], 'editable_sections': [], 'deletable_sections': []}).raise_for_status()
    assert client.get(endpoint, headers=manager).status_code == 403
