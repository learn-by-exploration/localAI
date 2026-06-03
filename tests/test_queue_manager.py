import asyncio
import pytest

from src.core.queue_manager import RequestQueue


@pytest.mark.asyncio
async def test_executes_task():
    queue = RequestQueue(max_concurrent=2)

    async def task():
        return 42

    result = await queue.execute(task)
    assert result == 42
    assert queue.total_processed == 1


@pytest.mark.asyncio
async def test_concurrent_limit():
    queue = RequestQueue(max_concurrent=1)
    order = []

    async def slow_task(name: str):
        order.append(f"{name}:start")
        await asyncio.sleep(0.05)
        order.append(f"{name}:end")
        return name

    results = await asyncio.gather(
        queue.execute(slow_task, "a"),
        queue.execute(slow_task, "b"),
    )
    assert set(results) == {"a", "b"}
    assert queue.total_processed == 2
    # With limit=1, second task must start after first ends
    assert order.index("a:end") < order.index("b:start")


@pytest.mark.asyncio
async def test_error_counts():
    queue = RequestQueue(max_concurrent=2)

    async def failing():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await queue.execute(failing)

    assert queue.total_errors == 1
    assert queue.total_processed == 0


@pytest.mark.asyncio
async def test_stats_format():
    queue = RequestQueue(max_concurrent=2)
    stats = queue.stats()
    assert "active" in stats
    assert "queued" in stats
    assert "total_processed" in stats
    assert "total_errors" in stats


@pytest.mark.asyncio
async def test_stream_slot_counts_processed():
    queue = RequestQueue(max_concurrent=1)

    async with queue.stream_slot():
        assert queue.active_requests == 1

    assert queue.active_requests == 0
    assert queue.queued_requests == 0
    assert queue.total_processed == 1


@pytest.mark.asyncio
async def test_stream_slot_cancel_while_queued_cleans_counter():
    queue = RequestQueue(max_concurrent=1)

    async def waiting_stream():
        async with queue.stream_slot():
            await asyncio.sleep(999)

    async with queue.stream_slot():
        task = asyncio.create_task(waiting_stream())
        while queue.queued_requests == 0:
            await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert queue.queued_requests == 0
        assert queue.active_requests == 1

    assert queue.active_requests == 0


@pytest.mark.asyncio
async def test_execute_cancel_while_queued_cleans_counter():
    queue = RequestQueue(max_concurrent=1)

    async def slow_task():
        await asyncio.sleep(999)

    first = asyncio.create_task(queue.execute(slow_task))
    while queue.active_requests == 0:
        await asyncio.sleep(0)

    second = asyncio.create_task(queue.execute(slow_task))
    while queue.queued_requests == 0:
        await asyncio.sleep(0)

    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    assert queue.queued_requests == 0

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert queue.active_requests == 0


@pytest.mark.asyncio
async def test_wait_until_idle_times_out_when_active():
    queue = RequestQueue(max_concurrent=1)

    async def slow_task():
        await asyncio.sleep(999)

    task = asyncio.create_task(queue.execute(slow_task))
    while queue.active_requests == 0:
        await asyncio.sleep(0)

    assert await queue.wait_until_idle(timeout_s=0.01) is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await queue.wait_until_idle(timeout_s=0.01) is True
