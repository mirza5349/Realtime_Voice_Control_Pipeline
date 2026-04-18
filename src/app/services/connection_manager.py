from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.models.events import ErrorEvent, ErrorPayload, ServerEventBase


class SessionConnectionExistsError(Exception):
    pass


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            if session_id in self._connections:
                raise SessionConnectionExistsError(
                    f"Session {session_id} already has an active connection"
                )
            await websocket.accept()
            self._connections[session_id] = websocket

    async def disconnect(self, session_id: UUID) -> None:
        async with self._lock:
            self._connections.pop(session_id, None)

    async def send_event(self, event: ServerEventBase) -> None:
        websocket = await self._get_connection(event.session_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(event.model_dump(mode="json"))
        except (RuntimeError, WebSocketDisconnect):
            await self.disconnect(event.session_id)

    async def send_error(self, session_id: UUID, code: str, message: str) -> None:
        await self.send_event(
            ErrorEvent(
                session_id=session_id,
                payload=ErrorPayload(code=code, message=message),
            )
        )

    async def broadcast_session(self, session_id: UUID, event: ServerEventBase) -> None:
        await self.send_event(event.model_copy(update={"session_id": session_id}))

    async def has_connection(self, session_id: UUID) -> bool:
        async with self._lock:
            return session_id in self._connections

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)

    async def _get_connection(self, session_id: UUID) -> WebSocket | None:
        async with self._lock:
            return self._connections.get(session_id)
