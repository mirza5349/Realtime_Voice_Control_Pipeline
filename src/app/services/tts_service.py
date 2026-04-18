from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from pydantic import ValidationError

from app.models.audio import AudioAsset
from app.models.tts import TTSRequest
from app.services.audio_store import AudioStore
from app.services.session_manager import SessionManager
from app.services.tts.base import TextToSpeechProvider, TTSProviderError


class TTSServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TTSService:
    def __init__(
        self,
        session_manager: SessionManager,
        tts_provider: TextToSpeechProvider,
        audio_store: AudioStore,
    ) -> None:
        self._session_manager = session_manager
        self._tts_provider = tts_provider
        self._audio_store = audio_store

    async def synthesize_assistant_response(
        self,
        session_id: UUID,
        request_id: UUID,
        text: str,
    ) -> AudioAsset:
        if self._session_manager.get_session(session_id) is None:
            raise TTSServiceError("session_not_found", "Session not found")

        try:
            request = TTSRequest(session_id=session_id, request_id=request_id, text=text)
        except ValidationError as error:
            raise TTSServiceError("tts_request_invalid", error.errors()[0]["msg"]) from error

        temp_path: Path | None = None

        try:
            with NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_path = Path(temp_file.name)
            synthesized_audio = await self._tts_provider.synthesize(request, temp_path)
            stored_asset = self._audio_store.store_file(
                session_id=session_id,
                request_id=request_id,
                source_path=synthesized_audio.file_path,
                content_type=synthesized_audio.content_type,
                duration_ms=synthesized_audio.duration_ms,
            )
        except TTSProviderError as error:
            raise TTSServiceError(error.code, error.message) from error
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        return AudioAsset(
            asset_id=stored_asset.asset_id,
            session_id=stored_asset.session_id,
            request_id=stored_asset.request_id,
            content_type=stored_asset.content_type,
            url=stored_asset.url,
            duration_ms=stored_asset.duration_ms,
            size_bytes=stored_asset.size_bytes,
            created_at=stored_asset.created_at,
            expires_at=stored_asset.expires_at,
        )
