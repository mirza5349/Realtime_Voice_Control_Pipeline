from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.models.live_audio import (
    LiveAudioControlResponse,
    LiveAudioErrorResponse,
    LiveAudioSubmissionResponse,
)
from app.services.live_audio_service import LiveAudioService, LiveAudioServiceError

router = APIRouter(prefix="/sessions", tags=["live_audio"])


def get_live_audio_service(request: Request) -> LiveAudioService:
    return request.app.state.live_audio_service


@router.post(
    "/{session_id}/live-audio/start",
    response_model=LiveAudioControlResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": LiveAudioErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": LiveAudioErrorResponse},
    },
)
async def start_live_audio(
    session_id: UUID,
    service: Annotated[LiveAudioService, Depends(get_live_audio_service)],
) -> LiveAudioControlResponse | JSONResponse:
    try:
        await service.start_session(session_id)
    except LiveAudioServiceError as error:
        return _error_response(error)
    return LiveAudioControlResponse(session_id=session_id, state="started")


@router.post(
    "/{session_id}/live-audio/stop",
    response_model=LiveAudioControlResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": LiveAudioErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": LiveAudioErrorResponse},
    },
)
async def stop_live_audio(
    session_id: UUID,
    service: Annotated[LiveAudioService, Depends(get_live_audio_service)],
) -> LiveAudioControlResponse | JSONResponse:
    try:
        await service.stop_session(session_id)
    except LiveAudioServiceError as error:
        return _error_response(error)
    return LiveAudioControlResponse(session_id=session_id, state="stopped")


@router.post(
    "/{session_id}/live-audio",
    response_model=LiveAudioSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": LiveAudioErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": LiveAudioErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": LiveAudioErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": LiveAudioErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": LiveAudioErrorResponse},
    },
)
async def submit_live_audio_utterance(
    session_id: UUID,
    file: Annotated[UploadFile, File(...)],
    duration_ms: Annotated[int, Form(ge=0)],
    service: Annotated[LiveAudioService, Depends(get_live_audio_service)],
) -> LiveAudioSubmissionResponse | JSONResponse:
    try:
        return await service.submit_utterance(
            session_id=session_id,
            upload=file,
            duration_ms=duration_ms,
        )
    except LiveAudioServiceError as error:
        return _error_response(error)


def _error_response(error: LiveAudioServiceError) -> JSONResponse:
    payload = LiveAudioErrorResponse(code=error.code, message=error.message)
    return JSONResponse(
        status_code=error.status_code,
        content=payload.model_dump(mode="json"),
    )
