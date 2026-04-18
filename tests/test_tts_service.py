import asyncio
import wave
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.tts import SynthesizedAudio, TTSRequest
from app.services.audio_store import AudioStore
from app.services.session_manager import SessionManager
from app.services.tts.base import TextToSpeechProvider, TTSExecutionError
from app.services.tts_service import TTSService, TTSServiceError


def write_wav(path: Path, duration_ms: int) -> None:
    frames = max(1, int(22050 * duration_ms / 1000))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * frames)


class FakeTTSProvider(TextToSpeechProvider):
    def __init__(self, duration_ms: int = 250) -> None:
        self.duration_ms = duration_ms

    async def synthesize(self, request: TTSRequest, output_path):  # type: ignore[override]
        write_wav(output_path, self.duration_ms)
        return SynthesizedAudio(
            provider="fake_tts",
            voice="test_voice",
            content_type="audio/wav",
            duration_ms=self.duration_ms,
            file_path=output_path,
        )


class FailingTTSProvider(TextToSpeechProvider):
    async def synthesize(self, request: TTSRequest, output_path):  # type: ignore[override]
        raise TTSExecutionError("piper failed")


def test_tts_service_stores_generated_audio_with_metadata(tmp_path: Path) -> None:
    session_manager = SessionManager()
    session = session_manager.create_session()
    service = TTSService(
        session_manager=session_manager,
        tts_provider=FakeTTSProvider(duration_ms=180),
        audio_store=AudioStore(tmp_path / "audio", "/api/v1/audio", 3600),
    )

    asset = asyncio.run(
        service.synthesize_assistant_response(
            session_id=session.session_id,
            request_id=uuid4(),
            text="Hello from Piper.",
        )
    )

    assert asset.session_id == session.session_id
    assert asset.content_type == "audio/wav"
    assert asset.duration_ms == 180
    assert asset.url == f"/api/v1/audio/{asset.asset_id}"
    assert asset.size_bytes > 0


def test_tts_service_raises_typed_error_for_provider_failures(tmp_path: Path) -> None:
    session_manager = SessionManager()
    session = session_manager.create_session()
    service = TTSService(
        session_manager=session_manager,
        tts_provider=FailingTTSProvider(),
        audio_store=AudioStore(tmp_path / "audio", "/api/v1/audio", 3600),
    )

    with pytest.raises(TTSServiceError) as error:
        asyncio.run(
            service.synthesize_assistant_response(
                session_id=session.session_id,
                request_id=uuid4(),
                text="Hello from Piper.",
            )
        )

    assert error.value.code == "tts_execution_failed"
    assert error.value.message == "piper failed"
