from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from app.models.session import CreateSessionRequest, Session
from app.services.session_manager import SessionManager

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: Annotated[CreateSessionRequest, Body()],
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> Session:
    return session_manager.create_session(payload)


@router.get("/{session_id}", response_model=Session)
def get_session(
    session_id: UUID,
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> Session:
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session
