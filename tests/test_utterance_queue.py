from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.utterance_queue import (
    UtteranceItem,
    UtteranceQueue,
    UtteranceQueueFullError,
)


def make_item(session_id, tmp_path: Path, index: int) -> UtteranceItem:
    path = tmp_path / f"item-{index}.bin"
    path.write_bytes(b"\x00")
    return UtteranceItem(
        session_id=session_id,
        request_id=uuid4(),
        audio_path=path,
        duration_ms=500 + index,
        content_type="audio/webm",
        filename=f"item-{index}.webm",
    )


def test_queue_processes_items_in_order(tmp_path: Path) -> None:
    async def scenario() -> tuple[list[int], int, list]:
        session_id = uuid4()
        processed: list[int] = []
        active = 0
        max_active = 0

        async def processor(item: UtteranceItem) -> None:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            processed.append(item.duration_ms)
            active -= 1

        idle_calls: list = []

        async def on_idle(sid) -> None:
            idle_calls.append(sid)

        queue = UtteranceQueue(
            processor=processor,
            max_depth_per_session=5,
            on_session_idle=on_idle,
        )
        for i in range(3):
            await queue.enqueue(make_item(session_id, tmp_path, i))
        await queue.wait_until_idle(session_id)
        await asyncio.sleep(0.02)
        await queue.shutdown()
        return processed, max_active, idle_calls

    processed, max_active, idle_calls = asyncio.run(scenario())
    assert processed == [500, 501, 502]
    assert max_active == 1
    assert idle_calls


def test_queue_rejects_when_full(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_id = uuid4()
        release = asyncio.Event()

        async def processor(item: UtteranceItem) -> None:
            await release.wait()

        queue = UtteranceQueue(
            processor=processor,
            max_depth_per_session=2,
            on_session_idle=None,
        )

        await queue.enqueue(make_item(session_id, tmp_path, 0))
        await asyncio.sleep(0.01)
        await queue.enqueue(make_item(session_id, tmp_path, 1))
        await queue.enqueue(make_item(session_id, tmp_path, 2))

        with pytest.raises(UtteranceQueueFullError):
            await queue.enqueue(make_item(session_id, tmp_path, 3))

        release.set()
        await queue.wait_until_idle(session_id)
        await queue.shutdown()

    asyncio.run(scenario())


def test_queue_isolates_sessions(tmp_path: Path) -> None:
    session_a = uuid4()
    session_b = uuid4()

    async def scenario() -> list[tuple]:
        processed: list[tuple] = []

        async def processor(item: UtteranceItem) -> None:
            processed.append((item.session_id, item.duration_ms))
            await asyncio.sleep(0.005)

        queue = UtteranceQueue(
            processor=processor,
            max_depth_per_session=3,
            on_session_idle=None,
        )
        await queue.enqueue(make_item(session_a, tmp_path, 0))
        await queue.enqueue(make_item(session_b, tmp_path, 10))
        await queue.enqueue(make_item(session_a, tmp_path, 1))
        await queue.enqueue(make_item(session_b, tmp_path, 11))
        await queue.wait_until_idle(session_a)
        await queue.wait_until_idle(session_b)
        await queue.shutdown()
        return processed

    processed = asyncio.run(scenario())
    a_items = [d for sid, d in processed if sid == session_a]
    b_items = [d for sid, d in processed if sid == session_b]
    assert a_items == [500, 501]
    assert b_items == [510, 511]


def test_queue_cleans_up_audio_files(tmp_path: Path) -> None:
    async def scenario() -> Path:
        session_id = uuid4()

        async def processor(item: UtteranceItem) -> None:
            assert item.audio_path.exists()

        queue = UtteranceQueue(
            processor=processor,
            max_depth_per_session=2,
            on_session_idle=None,
        )
        item = make_item(session_id, tmp_path, 0)
        await queue.enqueue(item)
        await queue.wait_until_idle(session_id)
        await queue.shutdown()
        return item.audio_path

    path = asyncio.run(scenario())
    assert not path.exists()


def test_queue_shutdown_session_allows_restart(tmp_path: Path) -> None:
    async def scenario() -> int:
        session_id = uuid4()
        processed: list[UtteranceItem] = []

        async def processor(item: UtteranceItem) -> None:
            processed.append(item)

        queue = UtteranceQueue(
            processor=processor,
            max_depth_per_session=2,
            on_session_idle=None,
        )
        await queue.enqueue(make_item(session_id, tmp_path, 0))
        await queue.wait_until_idle(session_id)
        await queue.shutdown_session(session_id)

        await queue.enqueue(make_item(session_id, tmp_path, 1))
        await queue.wait_until_idle(session_id)
        await queue.shutdown()
        return len(processed)

    count = asyncio.run(scenario())
    assert count == 2
