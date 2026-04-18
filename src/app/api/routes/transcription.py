from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.models.transcription import (
    TranscriptionErrorResponse,
    TranscriptionResponse,
    TranscriptionUploadRequest,
)
from app.services.transcription_service import TranscriptionService, TranscriptionServiceError

router = APIRouter(prefix="/sessions", tags=["transcriptions"])


def get_transcription_service(request: Request) -> TranscriptionService:
    return request.app.state.transcription_service


@router.post(
    "/{session_id}/transcriptions",
    response_model=TranscriptionResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": TranscriptionErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": TranscriptionErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": TranscriptionErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": TranscriptionErrorResponse},
    },
)
async def create_transcription(
    session_id: UUID,
    file: Annotated[UploadFile, File(...)],
    transcription_service: Annotated[TranscriptionService, Depends(get_transcription_service)],
) -> TranscriptionResponse | JSONResponse:
    request_model = TranscriptionUploadRequest(
        session_id=session_id,
        filename=file.filename or "upload.bin",
        content_type=file.content_type,
    )

    try:
        return await transcription_service.transcribe_upload(request_model, file)
    except TranscriptionServiceError as error:
        error_response = TranscriptionErrorResponse(code=error.code, message=error.message)
        return JSONResponse(
            status_code=error.status_code,
            content=error_response.model_dump(mode="json"),
        )
