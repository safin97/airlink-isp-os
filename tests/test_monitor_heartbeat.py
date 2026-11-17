import asyncio
from unittest.mock import MagicMock

import pytest

from monitoring import worker


def setup(monkeypatch):
    database = MagicMock()
    cache = MagicMock()
    monkeypatch.setattr(worker, 'SessionLocal', database)
    monkeypatch.setattr(worker, 'cache', cache)
    return database, cache


def test_slow_large_batch_reports_ready_before_all_devices_finish(monkeypatch):
    database, cache = setup(monkeypatch)
    original_wait = asyncio.wait
    async def fast_wait(tasks, timeout):
        assert timeout == 5
        return await original_wait(tasks, timeout=.001)
    monkeypatch.setattr(worker.asyncio, 'wait', fast_wait)
    async def scenario():
        release = asyncio.Event()
        completed = []
        active = 0
        maximum = 0
        async def poll(device_id, semaphore):
            nonlocal active, maximum
            async with semaphore:
                active += 1
                maximum = max(maximum, active)
                await release.wait()
                completed.append(device_id)
                active -= 1
        def heartbeat(key, value, ex):
            assert key == 'health:monitor' and ex == 180
            if cache.set.call_count <= 3:
                assert completed == []
            if cache.set.call_count == 3:
                release.set()
        monkeypatch.setattr(worker, 'poll', poll)
        cache.set.side_effect = heartbeat
        await worker.poll_devices(range(40), asyncio.Semaphore(8))
        assert sorted(completed) == list(range(40))
        assert maximum == 8
        assert cache.set.call_count >= 3
    asyncio.run(scenario())
    assert database.return_value.__enter__.return_value.execute.call_count == cache.set.call_count


def test_empty_inventory_reports_scheduler_ready(monkeypatch):
    database, cache = setup(monkeypatch)
    async def scenario():
        await worker.poll_devices([], asyncio.Semaphore(8))
    asyncio.run(scenario())
    cache.set.assert_called_once()
    database.return_value.__enter__.return_value.execute.assert_called_once()


@pytest.mark.parametrize('failure', ['database', 'redis', 'poll'])
def test_failed_readiness_or_poll_cancels_remaining_work(monkeypatch, failure):
    database, cache = setup(monkeypatch)
    if failure == 'database':
        database.return_value.__enter__.side_effect = RuntimeError('database unavailable')
    elif failure == 'redis':
        cache.set.side_effect = RuntimeError('redis unavailable')
    async def scenario():
        async def poll(device_id, semaphore):
            if failure == 'poll' and device_id == 0:
                raise RuntimeError('poll failed')
            await asyncio.Event().wait()
        monkeypatch.setattr(worker, 'poll', poll)
        with pytest.raises(RuntimeError):
            await worker.poll_devices(range(3), asyncio.Semaphore(8))
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(scenario())
    if failure == 'database':
        cache.set.assert_not_called()


def test_shutdown_cancels_inflight_polls(monkeypatch):
    setup(monkeypatch)
    async def scenario():
        started = asyncio.Event()
        stopped = []
        async def poll(device_id, semaphore):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(device_id)
        monkeypatch.setattr(worker, 'poll', poll)
        task = asyncio.create_task(worker.poll_devices([1, 2], asyncio.Semaphore(8)))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sorted(stopped) == [1, 2]
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(scenario())
