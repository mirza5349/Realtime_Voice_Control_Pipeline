from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, status
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.models.events import bind_client_event, parse_client_event
from app.services.connection_manager import SessionConnectionExistsError
from app.services.session_manager import SessionManager
from app.services.session_runtime import SessionNotFoundError, SessionRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws/sessions", tags=["ws"])


def _validation_message(error: ValidationError) -> str:
    details = error.errors()
    if not details:
        return "Invalid event payload"
    first_error = details[0]
    location = ".".join(str(part) for part in first_error["loc"])
    message = first_error["msg"]
    if location:
        return f"{location}: {message}"
    return message


@router.websocket("/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: UUID) -> None:
    session_manager: SessionManager = websocket.app.state.session_manager
    session_runtime: SessionRuntime = websocket.app.state.session_runtime

    if session_manager.get_session(session_id) is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Session not found",
        )
        return

    try:
        await session_runtime.connect(session_id, websocket)
    except SessionConnectionExistsError:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Session already connected",
        )
        return
    except SessionNotFoundError:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Session not found",
        )
        return

    logger.info("event=ws_connect session_id=%s", session_id)

    try:
        while True:
            try:
                raw_event = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                await session_runtime.send_error(
                    session_id,
                    code="invalid_json",
                    message="Message must be valid JSON",
                )
                continue

            try:
                client_event = parse_client_event(raw_event)
                client_event = bind_client_event(client_event, session_id)
            except ValidationError as error:
                await session_runtime.send_error(
                    session_id,
                    code="invalid_event",
                    message=_validation_message(error),
                )
                continue
            except ValueError as error:
                await session_runtime.send_error(
                    session_id,
                    code="invalid_event",
                    message=str(error),
                )
                continue

            await session_runtime.publish(client_event)
    finally:
        await session_runtime.disconnect(session_id)
        logger.info("event=ws_disconnect session_id=%s", session_id)
