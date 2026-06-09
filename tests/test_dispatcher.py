import asyncio

import pytest
from src.dispatcher.debounce import DebounceMap
from src.dispatcher.locks import FileLockMap


@pytest.mark.asyncio
async def test_debounce_fires_after_delay():
    fired = []
    dm = DebounceMap(default_delay=0.05)
    dm.schedule("a.md", lambda: fired.append("a"), delay=0.05)
    await asyncio.sleep(0.12)
    assert fired == ["a"]


@pytest.mark.asyncio
async def test_debounce_resets_on_repeat():
    fired = []
    dm = DebounceMap(default_delay=0.1)
    dm.schedule("b.md", lambda: fired.append("b"), delay=0.1)
    await asyncio.sleep(0.05)
    dm.schedule("b.md", lambda: fired.append("b"), delay=0.1)
    await asyncio.sleep(0.05)
    assert fired == []
    await asyncio.sleep(0.15)
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_debounce_cancel():
    fired = []
    dm = DebounceMap(default_delay=0.1)
    dm.schedule("c.md", lambda: fired.append("c"), delay=0.1)
    dm.cancel("c.md")
    await asyncio.sleep(0.15)
    assert fired == []


@pytest.mark.asyncio
async def test_file_lock_serializes():
    locks = FileLockMap()
    order = []

    async def task(name):
        async with locks.acquire("same.md"):
            order.append(f"start-{name}")
            await asyncio.sleep(0.02)
            order.append(f"end-{name}")

    await asyncio.gather(task("a"), task("b"))
    # One must fully complete before the other starts
    assert (order.index("end-a") < order.index("start-b")) or (
        order.index("end-b") < order.index("start-a")
    )


@pytest.mark.asyncio
async def test_file_lock_different_paths_concurrent():
    locks = FileLockMap()
    results = []

    async def task(path):
        async with locks.acquire(path):
            await asyncio.sleep(0.02)
            results.append(path)

    await asyncio.gather(task("a.md"), task("b.md"))
    assert len(results) == 2
