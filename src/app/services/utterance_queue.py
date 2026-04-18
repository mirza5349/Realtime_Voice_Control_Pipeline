from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)


class UtteranceQueueFullError(Exception):
    def __init__(self, session_id: UUID, max_depth: int) -> None:
        super().__init__(f"Utterance queue is full for session {session_id}")
        self.session_id = session_id
        self.max_depth = max_depth


@dataclass(slots=True)
class UtteranceItem:
    session_id: UUID
    request_id: UUID
    audio_path: Path
    duration_ms: int
    content_type: str
    filename: str


UtteranceProcessor = Callable[[UtteranceItem], Awaitable[None]]
SessionCallback = Callable[[UUID], Awaitable[None]]


class UtteranceQueue:
    def __init__(
        self,
        processor: UtteranceProcessor,
        max_depth_per_session: int,
        on_session_idle: SessionCallback | None = None,
    ) -> None:
        if max_depth_per_session < 1:
            raise ValueError("max_depth_per_session must be >= 1")
        self._processor = processor
        self._max_depth = max_depth_per_session
        self._on_session_idle = on_session_idle
        self._queues: dict[UUID, asyncio.Queue[UtteranceItem | None]] = {}
        self._workers: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, item: UtteranceItem) -> int:
        async with self._lock:
            queue = self._queues.get(item.session_id)
            if queue is None:
                queue = asyncio.Queue(maxsize=self._max_depth)
                self._queues[item.session_id] = queue
                self._workers[item.session_id] = asyncio.create_task(
                    self._worker(item.session_id, queue)
                )
            if queue.full():
                raise UtteranceQueueFullError(item.session_id, self._max_depth)
            queue.put_nowait(item)
            return queue.qsize()

    async def qsize(self, session_id: UUID) -> int:
        async with self._lock:
            queue = self._queues.get(session_id)
            return queue.qsize() if queue is not None else 0

    async def wait_until_idle(self, session_id: UUID) -> None:
        async with self._lock:
            queue = self._queues.get(session_id)
        if queue is None:
            return
        await queue.join()

    async def shutdown_session(self, session_id: UUID) -> None:
        async with self._lock:
            queue = self._queues.pop(session_id, None)
            worker = self._workers.pop(session_id, None)
        if queue is not None:
            queue.put_nowait(None)
        if worker is not None:
            try:
                await worker
            except asyncio.CancelledError:
                pass

    async def shutdown(self) -> None:
        async with self._lock:
            session_ids = list(self._queues.keys())
        for session_id in session_ids:
            await self.shutdown_session(session_id)

    async def _worker(
        self,
        session_id: UUID,
        queue: asyncio.Queue[UtteranceItem | None],
    ) -> None:
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            try:
                await self._processor(item)
            except asyncio.CancelledError:
                queue.task_done()
                raise
            except Exception as error:
                logger.exception(
                    "event=utterance_processor_error session_id=%s request_id=%s detail=%s",
                    item.session_id,
                    item.request_id,
                    error,
                )
            finally:
                queue.task_done()
                item.audio_path.unlink(missing_ok=True)

            if queue.empty() and self._on_session_idle is not None:
                try:
                    await self._on_session_idle(session_id)
                except Exception as error:
                    logger.warning(
                        "event=utterance_idle_callback_error session_id=%s detail=%s",
                        session_id,
                        error,
                    )
