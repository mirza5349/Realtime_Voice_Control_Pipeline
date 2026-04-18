import wave
from io import BytesIO
from pathlib import Path

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.action import ActionDecision, ActionName
from app.models.llm import LLMGenerationResult
from app.models.transcription import TranscriptionResult
from app.models.tts import SynthesizedAudio, TTSRequest
from app.services.audio_store import AudioStore
from app.services.llm.base import LLMProvider
from app.services.orchestrator import Orchestrator
from app.services.prompt_builder import PromptBuilder
from app.services.stt.base import SpeechToTextAdapter
from app.services.transcription_service import TranscriptionService
from app.services.tts.base import TextToSpeechProvider, TTSExecutionError
from app.services.tts_service import TTSService


def write_wav(path: Path, duration_ms: int) -> None:
    frames = max(1, int(22050 * duration_ms / 1000))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * frames)


class FakeSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text="status report",
            language="en",
            duration_ms=42,
            provider="fake_stt",
        )


class FakeLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        return LLMGenerationResult(
            assistant_text="All systems look good.",
            action=ActionDecision(name=ActionName.STATUS_REPORT, parameters={}),
            provider="fake_llm",
            model="fake-model",
            duration_ms=18,
        )


class FakeTTSProvider(TextToSpeechProvider):
    async def synthesize(self, request: TTSRequest, output_path):  # type: ignore[override]
        write_wav(output_path, 210)
        return SynthesizedAudio(
            provider="fake_tts",
            voice="test_voice",
            content_type="audio/wav",
            duration_ms=210,
            file_path=output_path,
        )


class FailingTTSProvider(TextToSpeechProvider):
    async def synthesize(self, request: TTSRequest, output_path):  # type: ignore[override]
        raise TTSExecutionError("piper failed")


def install_runtime(
    client: TestClient,
    tmp_path: Path,
    tts_provider: TextToSpeechProvider,
) -> None:
    orchestrator = Orchestrator(
        llm_provider=FakeLLMProvider(),
        prompt_builder=PromptBuilder(),
        history_limit=10,
    )
    audio_store = AudioStore(tmp_path / "audio", "/api/v1/audio", 3600)
    tts_service = TTSService(
        session_manager=client.app.state.session_manager,
        tts_provider=tts_provider,
        audio_store=audio_store,
    )
    client.app.state.audio_store = audio_store
    client.app.state.orchestrator = orchestrator
    client.app.state.tts_service = tts_service
    client.app.state.session_runtime.set_orchestrator(orchestrator)
    client.app.state.session_runtime.set_execution_service(None)
    client.app.state.session_runtime.set_tts_service(tts_service)
    client.app.state.transcription_service = TranscriptionService(
        session_manager=client.app.state.session_manager,
        session_runtime=client.app.state.session_runtime,
        stt_adapter=FakeSpeechToTextAdapter(),
        upload_max_bytes=1024 * 1024,
    )


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["session_id"]


def test_assistant_response_triggers_tts_and_audio_ready_event(tmp_path: Path) -> None:
    with TestClient(app) as client:
        install_runtime(client, tmp_path, FakeTTSProvider())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            websocket.receive_json()
            transcription_completed = websocket.receive_json()
            websocket.receive_json()
            websocket.receive_json()
            assistant_response = websocket.receive_json()
            tts_started = websocket.receive_json()
            tts_completed = websocket.receive_json()
            audio_ready = websocket.receive_json()
            action_decided = websocket.receive_json()

            audio_response = client.get(audio_ready["payload"]["url"])

    assert response.status_code == status.HTTP_200_OK
    assert transcription_completed["type"] == "transcription.completed"
    assert assistant_response == {
        "type": "assistant.response",
        "session_id": session_id,
        "timestamp": assistant_response["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "text": "All systems look good.",
        },
    }
    assert tts_started == {
        "type": "tts.started",
        "session_id": session_id,
        "timestamp": tts_started["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "text_length": len("All systems look good."),
        },
    }
    assert tts_completed == {
        "type": "tts.completed",
        "session_id": session_id,
        "timestamp": tts_completed["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "asset_id": tts_completed["payload"]["asset_id"],
            "duration_ms": 210,
        },
    }
    assert audio_ready == {
        "type": "assistant.audio_ready",
        "session_id": session_id,
        "timestamp": audio_ready["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "asset_id": tts_completed["payload"]["asset_id"],
            "url": audio_ready["payload"]["url"],
            "content_type": "audio/wav",
        },
    }
    assert audio_ready["payload"]["url"] == f"/api/v1/audio/{tts_completed['payload']['asset_id']}"
    assert action_decided["type"] == "action.decided"
    assert audio_response.status_code == status.HTTP_200_OK
    assert audio_response.headers["content-type"].startswith("audio/wav")
    assert len(audio_response.content) > 0


def test_tts_failure_emits_error_and_keeps_action_flow_alive(tmp_path: Path) -> None:
    with TestClient(app) as client:
        install_runtime(client, tmp_path, FailingTTSProvider())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            websocket.receive_json()
            transcription_completed = websocket.receive_json()
            websocket.receive_json()
            websocket.receive_json()
            websocket.receive_json()
            tts_started = websocket.receive_json()
            error_event = websocket.receive_json()
            action_decided = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert transcription_completed["type"] == "transcription.completed"
    assert tts_started["type"] == "tts.started"
    assert error_event == {
        "type": "error",
        "session_id": session_id,
        "timestamp": error_event["timestamp"],
        "payload": {
            "code": "tts_execution_failed",
            "message": "piper failed",
        },
    }
    assert action_decided["type"] == "action.decided"
