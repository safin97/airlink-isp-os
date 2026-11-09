import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import fakeredis
import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text

from airlink import device_api
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from monitoring import worker, snmp
from test_api import tower, user


def test_device_timing_saved_and_updates_schedule(client, owner):
    tid = tower(client, owner)
    data = {'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.1'}
    saved = client.post('/api/devices', headers=owner, json=data)
    assert saved.status_code == 201
    assert saved.json()['connection_timeout'] == 2
    assert saved.json()['poll_interval'] == 60
    did = saved.json()['id']
    with SessionLocal() as db:
        db.get(Device, did).last_poll = now()
        db.commit()
    data.update(connection_timeout=8, poll_interval=120)
    changed = client.put('/api/devices/' + did, headers=owner, json=data)
    assert changed.status_code == 200
    result = client.get('/api/devices', headers=owner).json()[0]
    assert result['connection_timeout'] == 8 and result['poll_interval'] == 120
    assert result['last_poll'] is None


@pytest.mark.parametrize('field,value', [('connection_timeout', 0), ('connection_timeout', 31),
    ('connection_timeout', 1.5), ('poll_interval', 14), ('poll_interval', 86401)])
def test_invalid_device_timing(client, owner, field, value):
    tid = tower(client, owner)
    assert client.post('/api/devices', headers=owner, json={
        'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.1', field: value}).status_code == 422


def test_manager_cannot_change_timeout(client, owner):
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    data = {'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.1', 'connection_timeout': 8}
    assert client.post('/api/devices', headers=manager, json=data).status_code == 403
    did = client.post('/api/devices', headers=owner, json=data).json()['id']
    assert client.put('/api/devices/' + did, headers=manager, json=data).status_code == 200
    data['connection_timeout'] = 9
    assert client.put('/api/devices/' + did, headers=manager, json=data).status_code == 403


@pytest.mark.parametrize('change_during_poll', [False, True])
def test_worker_passes_timeout_and_discards_changed_settings(client, owner, monkeypatch, change_during_poll):
    tid = client.post('/api/towers', headers=owner, json={
        'name': 'North', 'api_enabled': True, 'api_username': 'monitor', 'api_password': 'test-secret'}).json()['id']
    profile = client.post('/api/snmp-profiles/discovery-public', headers=owner, json={'version': '2c'}).json()['id']
    data = {'tower_id': tid, 'name': 'Radio', 'ip_address': '192.0.2.1',
            'snmp_profile_id': profile, 'connection_timeout': 8, 'poll_interval': 120}
    did = client.post('/api/devices', headers=owner, json=data).json()['id']
    cache = fakeredis.FakeRedis()
    monkeypatch.setattr(worker, 'cache', cache)
    ping = AsyncMock(return_value=True)
    collect = AsyncMock(return_value={'snmp_up': True})
    async def api(*args, **kwargs):
        if change_during_poll:
            assert client.put('/api/devices/' + did, headers=owner,
                json={**data, 'connection_timeout': 9}).status_code == 200
        return {}
    probe = AsyncMock(side_effect=api)
    monkeypatch.setattr(worker, 'ping', ping)
    monkeypatch.setattr(worker, 'collect', collect)
    monkeypatch.setattr(worker, 'collect_api', probe)
    async def poll():
        await worker.poll(did, asyncio.Semaphore(1))
    asyncio.run(poll())
    for call in (ping, collect, probe):
        assert call.await_args.kwargs['timeout'] == 8
    assert not cache.exists('poll:' + did)
    with SessionLocal() as db:
        metric = db.scalar(select(Metric).where(Metric.device_id == did))
        assert (metric is None) == change_during_poll


@pytest.mark.parametrize('platform,milliseconds', [('darwin', True), ('linux', False)])
def test_ping_timeout_and_cancel_reaps_child(monkeypatch, platform, milliseconds):
    async def run():
        started = asyncio.Event()
        proc = Mock(returncode=None)
        async def wait():
            if proc.returncode is None:
                started.set()
                await asyncio.Event().wait()
            return proc.returncode
        def kill():
            proc.returncode = -9
        proc.wait = AsyncMock(side_effect=wait)
        proc.kill = Mock(side_effect=kill)
        spawn = AsyncMock(return_value=proc)
        monkeypatch.setattr(worker.sys, 'platform', platform)
        monkeypatch.setattr(worker.asyncio, 'create_subprocess_exec', spawn)
        task = asyncio.create_task(worker.ping('192.0.2.1', 2, timeout=8))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert spawn.call_args.args[-2] == ('8000' if milliseconds else '8')
        proc.kill.assert_called_once()
        assert proc.wait.await_count == 2
    asyncio.run(run())


def test_transport_timeouts(monkeypatch):
    target = AsyncMock(return_value=object())
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', target)
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=('unavailable', None, None, [])))
    with pytest.raises(RuntimeError):
        asyncio.run(snmp.collect('192.0.2.1', {'version': '2c', 'community': 'public'}, 2, timeout=8))
    assert target.await_args.kwargs == {'timeout': 8, 'retries': 2}
    requests = []
    def handle(request):
        requests.append(request)
        assert request.extensions['timeout'] == dict(connect=8, read=8, write=8, pool=8)
        return httpx.Response(200, text='unsupported device')
    with pytest.raises(RuntimeError):
        asyncio.run(device_api.collect_api('192.0.2.1', {}, timeout=8, transport=httpx.MockTransport(handle)))
    assert len(requests) == 1


def test_timeout_migration_preserves_existing_devices(tmp_path):
    spec = importlib.util.spec_from_file_location('timeout_migration',
        Path(__file__).resolve().parents[1] / 'database/versions/62b4c9d8e731_device_connection_timeout.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE devices (id TEXT PRIMARY KEY, poll_interval INTEGER NOT NULL)'))
        connection.execute(text("INSERT INTO devices VALUES ('saved-radio', 120)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text('SELECT * FROM devices')).one() == ('saved-radio', 120, 2)
        migration.downgrade()
        assert connection.execute(text('SELECT * FROM devices')).one() == ('saved-radio', 120)
    engine.dispose()
