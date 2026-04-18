from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import UploadFile, status

from app.models.transcription import (
    TranscriptionResponse,
    TranscriptionUploadRequest,
)
from app.services.session_manager import SessionManager
from app.services.session_runtime import SessionRuntime
from app.services.stt.base import SpeechToTextAdapter, STTAdapterError

ALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".oga",
    ".ogg",
    ".wav",
    ".webm",
}


class TranscriptionServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class TranscriptionService:
    def __init__(
        self,
        session_manager: SessionManager,
        session_runtime: SessionRuntime,
        stt_adapter: SpeechToTextAdapter,
        upload_max_bytes: int,
    ) -> None:
        self._session_manager = session_manager
        self._session_runtime = session_runtime
        self._stt_adapter = stt_adapter
        self._upload_max_bytes = upload_max_bytes

    async def transcribe_upload(
        self,
        request: TranscriptionUploadRequest,
        upload: UploadFile,
    ) -> TranscriptionResponse:
        if self._session_manager.get_session(request.session_id) is None:
            raise TranscriptionServiceError(
                status.HTTP_404_NOT_FOUND,
                "session_not_found",
                "Session not found",
            )

        if not self._is_supported_audio_upload(request):
            raise TranscriptionServiceError(
                status.HTTP_400_BAD_REQUEST,
                "invalid_audio_type",
                "Unsupported audio upload",
            )

        request_id = uuid4()
        temp_path: Path | None = None

        try:
            temp_path = await self._persist_upload(request, upload)
            await self._session_runtime.send_transcription_started(request.session_id, request_id)
            result = await self._stt_adapter.transcribe_file(temp_path)
        except STTAdapterError as error:
            await self._session_runtime.send_error(
                request.session_id,
                code="transcription_failed",
                message=str(error),
                request_id=request_id,
            )
            raise TranscriptionServiceError(
                status.HTTP_502_BAD_GATEWAY,
                "transcription_failed",
                str(error),
            ) from error
        finally:
            await upload.close()
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        await self._session_runtime.handle_transcription_completed(
            request.session_id,
            request_id,
            result,
        )

        return TranscriptionResponse(
            session_id=request.session_id,
            request_id=request_id,
            text=result.text,
            language=result.language,
            duration_ms=result.duration_ms,
            provider=result.provider,
        )

    def _is_supported_audio_upload(self, request: TranscriptionUploadRequest) -> bool:
        content_type = request.content_type or ""
        if content_type.startswith("audio/"):
            return True
        return Path(request.filename).suffix.lower() in ALLOWED_AUDIO_EXTENSIONS

    async def _persist_upload(
        self,
        request: TranscriptionUploadRequest,
        upload: UploadFile,
    ) -> Path:
        suffix = Path(request.filename).suffix or ".bin"
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)

        bytes_written = 0

        try:
            with temp_path.open("wb") as output_file:
                while chunk := await upload.read(1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > self._upload_max_bytes:
                        raise TranscriptionServiceError(
                            status.HTTP_413_CONTENT_TOO_LARGE,
                            "upload_too_large",
                            "Audio upload exceeds configured size limit",
                        )
                    output_file.write(chunk)

            if bytes_written == 0:
                raise TranscriptionServiceError(
                    status.HTTP_400_BAD_REQUEST,
                    "empty_upload",
                    "Audio upload is empty",
                )

            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
