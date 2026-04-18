from io import BytesIO

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.action import ActionDecision, ActionName
from app.models.llm import LLMGenerationResult
from app.models.transcription import TranscriptionResult
from app.models.tts import SynthesizedAudio, TTSRequest
from app.services.llm.base import LLMProvider, LLMResponseError
from app.services.orchestrator import Orchestrator
from app.services.prompt_builder import PromptBuilder
from app.services.stt.base import SpeechToTextAdapter
from app.services.transcription_service import TranscriptionService
from app.services.tts.base import TextToSpeechProvider
from app.services.tts_service import TTSService


class FakeSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text="move forward",
            language="en",
            duration_ms=42,
            provider="fake_stt",
        )


class FakeLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        return LLMGenerationResult(
            assistant_text="Moving forward now.",
            action=ActionDecision(name=ActionName.MOVE_FORWARD, parameters={"distance_m": 1}),
            provider="fake_llm",
            model="fake-model",
            duration_ms=18,
        )


class FailingLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        raise LLMResponseError("Model returned invalid structured output")


class SilentTTSProvider(TextToSpeechProvider):
    async def synthesize(self, request: TTSRequest, output_path):  # type: ignore[override]
        return SynthesizedAudio(
            provider="fake_tts",
            voice="silent",
            content_type="audio/wav",
            duration_ms=0,
            file_path=output_path,
        )


def install_runtime(client: TestClient, llm_provider: LLMProvider) -> None:
    orchestrator = Orchestrator(
        llm_provider=llm_provider,
        prompt_builder=PromptBuilder(),
        history_limit=10,
    )
    client.app.state.orchestrator = orchestrator
    client.app.state.session_runtime.set_orchestrator(orchestrator)
    client.app.state.tts_service = TTSService(
        session_manager=client.app.state.session_manager,
        tts_provider=SilentTTSProvider(),
        audio_store=client.app.state.audio_store,
    )
    client.app.state.session_runtime.set_tts_service(None)
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


def test_llm_events_follow_transcription_completion() -> None:
    with TestClient(app) as client:
        install_runtime(client, FakeLLMProvider())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            transcription_started = websocket.receive_json()
            transcription_completed = websocket.receive_json()
            llm_started = websocket.receive_json()
            llm_completed = websocket.receive_json()
            assistant_response = websocket.receive_json()
            action_decided = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert transcription_started["type"] == "transcription.started"
    assert transcription_completed["type"] == "transcription.completed"
    assert llm_started == {
        "type": "llm.started",
        "session_id": session_id,
        "timestamp": llm_started["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
        },
    }
    assert llm_completed == {
        "type": "llm.completed",
        "session_id": session_id,
        "timestamp": llm_completed["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "duration_ms": 18,
        },
    }
    assert assistant_response == {
        "type": "assistant.response",
        "session_id": session_id,
        "timestamp": assistant_response["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "text": "Moving forward now.",
        },
    }
    assert action_decided == {
        "type": "action.decided",
        "session_id": session_id,
        "timestamp": action_decided["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "action": {
                "name": "move_forward",
                "parameters": {"distance_m": 1},
            },
        },
    }


def test_llm_failures_emit_error_without_failing_transcription_response() -> None:
    with TestClient(app) as client:
        install_runtime(client, FailingLLMProvider())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            websocket.receive_json()
            transcription_completed = websocket.receive_json()
            llm_started = websocket.receive_json()
            error_event = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert transcription_completed["type"] == "transcription.completed"
    assert llm_started["type"] == "llm.started"
    assert error_event == {
        "type": "error",
        "session_id": session_id,
        "timestamp": error_event["timestamp"],
        "payload": {
            "code": "llm_response_invalid",
            "message": "Model returned invalid structured output",
        },
    }
