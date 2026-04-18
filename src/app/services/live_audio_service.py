from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from fastapi import UploadFile, status

from app.core.config import Settings
from app.models.live_audio import LiveAudioConfig, LiveAudioSubmissionResponse
from app.services.session_manager import SessionManager
from app.services.session_runtime import SessionRuntime
from app.services.stt.base import SpeechToTextAdapter, STTAdapterError
from app.services.utterance_queue import (
    UtteranceItem,
    UtteranceQueue,
    UtteranceQueueFullError,
)

logger = logging.getLogger(__name__)

ALLOWED_LIVE_AUDIO_EXTENSIONS = {
    ".wav",
    ".webm",
    ".ogg",
    ".oga",
    ".mp3",
    ".m4a",
    ".mp4",
    ".flac",
    ".aac",
}


class LiveAudioServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class LiveAudioService:
    def __init__(
        self,
        settings: Settings,
        session_manager: SessionManager,
        session_runtime: SessionRuntime,
        stt_adapter: SpeechToTextAdapter,
        utterance_queue: UtteranceQueue,
    ) -> None:
        self._settings = settings
        self._session_manager = session_manager
        self._session_runtime = session_runtime
        self._stt_adapter = stt_adapter
        self._queue = utterance_queue

    @property
    def queue(self) -> UtteranceQueue:
        return self._queue

    def config(self) -> LiveAudioConfig:
        prefix = self._settings.app_api_v1_prefix.rstrip("/")
        return LiveAudioConfig(
            enabled=self._settings.live_audio_enabled,
            max_seconds_per_utterance=self._settings.live_audio_max_seconds_per_utterance,
            min_seconds_per_utterance=self._settings.live_audio_min_seconds_per_utterance,
            max_queue_per_session=self._settings.live_audio_max_queue_per_session,
            autoplay_default=self._settings.live_audio_autoplay_default,
            silence_window_ms=self._settings.live_audio_silence_window_ms,
            submit_path=f"{prefix}/sessions/{{session_id}}/live-audio",
        )

    async def start_session(self, session_id: UUID) -> None:
        self._require_enabled()
        self._require_session(session_id)
        await self._session_runtime.send_live_audio_started(session_id)

    async def stop_session(self, session_id: UUID) -> None:
        self._require_enabled()
        self._require_session(session_id)
        await self._session_runtime.send_live_audio_idle(session_id)

    async def submit_utterance(
        self,
        session_id: UUID,
        upload: UploadFile,
        duration_ms: int,
    ) -> LiveAudioSubmissionResponse:
        self._require_enabled()
        self._require_session(session_id)
        self._validate_duration(duration_ms)
        self._validate_upload(upload)

        request_id = uuid4()
        temp_path = await self._persist_upload(upload)

        item = UtteranceItem(
            session_id=session_id,
            request_id=request_id,
            audio_path=temp_path,
            duration_ms=duration_ms,
            content_type=upload.content_type or "audio/webm",
            filename=upload.filename or "utterance.webm",
        )

        await self._session_runtime.send_live_audio_utterance_captured(
            session_id=session_id,
            request_id=request_id,
            duration_ms=duration_ms,
        )

        try:
            queued_position = await self._queue.enqueue(item)
        except UtteranceQueueFullError as error:
            temp_path.unlink(missing_ok=True)
            raise LiveAudioServiceError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "live_audio_queue_full",
                "Live audio queue is full for this session",
            ) from error

        return LiveAudioSubmissionResponse(
            session_id=session_id,
            request_id=request_id,
            duration_ms=duration_ms,
            queued_position=queued_position,
        )

    async def process_utterance(self, item: UtteranceItem) -> None:
        await self._session_runtime.send_live_audio_processing_started(
            session_id=item.session_id,
            request_id=item.request_id,
        )
        await self._session_runtime.send_transcription_started(
            item.session_id, item.request_id
        )

        try:
            result = await self._stt_adapter.transcribe_file(item.audio_path)
        except STTAdapterError as error:
            logger.warning(
                "event=live_audio_transcription_failed session_id=%s request_id=%s detail=%s",
                item.session_id,
                item.request_id,
                error,
            )
            await self._session_runtime.send_error(
                item.session_id,
                code="transcription_failed",
                message=str(error),
                request_id=item.request_id,
            )
            await self._session_runtime.send_live_audio_processing_completed(
                session_id=item.session_id,
                request_id=item.request_id,
                status="failed",
            )
            return

        await self._session_runtime.handle_transcription_completed(
            item.session_id,
            item.request_id,
            result,
        )
        await self._session_runtime.send_live_audio_processing_completed(
            session_id=item.session_id,
            request_id=item.request_id,
            status="completed",
        )

    async def on_session_idle(self, session_id: UUID) -> None:
        await self._session_runtime.send_live_audio_idle(session_id)

    def _require_enabled(self) -> None:
        if not self._settings.live_audio_enabled:
            raise LiveAudioServiceError(
                status.HTTP_403_FORBIDDEN,
                "live_audio_disabled",
                "Live audio capture is disabled",
            )

    def _require_session(self, session_id: UUID) -> None:
        if self._session_manager.get_session(session_id) is None:
            raise LiveAudioServiceError(
                status.HTTP_404_NOT_FOUND,
                "session_not_found",
                "Session not found",
            )

    def _validate_duration(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise LiveAudioServiceError(
                status.HTTP_400_BAD_REQUEST,
                "invalid_utterance_duration",
                "Utterance duration must be non-negative",
            )
        max_ms = int(self._settings.live_audio_max_seconds_per_utterance * 1000)
        min_ms = int(self._settings.live_audio_min_seconds_per_utterance * 1000)
        if duration_ms > max_ms:
            raise LiveAudioServiceError(
                status.HTTP_400_BAD_REQUEST,
                "utterance_too_long",
                f"Utterance exceeds max duration of {max_ms} ms",
            )
        if duration_ms and duration_ms < min_ms:
            raise LiveAudioServiceError(
                status.HTTP_400_BAD_REQUEST,
                "utterance_too_short",
                f"Utterance shorter than min duration of {min_ms} ms",
            )

    def _validate_upload(self, upload: UploadFile) -> None:
        content_type = (upload.content_type or "").lower()
        filename = upload.filename or ""
        if content_type.startswith("audio/"):
            return
        suffix = Path(filename).suffix.lower()
        if suffix in ALLOWED_LIVE_AUDIO_EXTENSIONS:
            return
        raise LiveAudioServiceError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_audio_type",
            "Unsupported live audio upload",
        )

    async def _persist_upload(self, upload: UploadFile) -> Path:
        suffix = Path(upload.filename or "utterance.webm").suffix or ".webm"
        max_bytes = self._settings.upload_max_bytes

        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)

        bytes_written = 0
        try:
            with temp_path.open("wb") as output_file:
                while chunk := await upload.read(1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise LiveAudioServiceError(
                            status.HTTP_413_CONTENT_TOO_LARGE,
                            "upload_too_large",
                            "Live audio upload exceeds configured size limit",
                        )
                    output_file.write(chunk)

            if bytes_written == 0:
                raise LiveAudioServiceError(
                    status.HTTP_400_BAD_REQUEST,
                    "empty_upload",
                    "Live audio upload is empty",
                )
            return temp_path
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
