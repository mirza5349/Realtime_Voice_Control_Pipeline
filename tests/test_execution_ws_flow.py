from io import BytesIO

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.action import ActionDecision, ActionName
from app.models.llm import LLMGenerationResult
from app.models.transcription import TranscriptionResult
from app.models.tts import SynthesizedAudio, TTSRequest
from app.services.execution_service import ExecutionService
from app.services.llm.base import LLMProvider
from app.services.orchestrator import Orchestrator
from app.services.prompt_builder import PromptBuilder
from app.services.simulator.low_fidelity import LowFidelitySimulator
from app.services.stt.base import SpeechToTextAdapter
from app.services.transcription_service import TranscriptionService
from app.services.tts.base import TextToSpeechProvider
from app.services.tts_service import TTSService


class FakeSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text="turn right",
            language="en",
            duration_ms=42,
            provider="fake_stt",
        )


class FakeLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        return LLMGenerationResult(
            assistant_text="Turning right.",
            action=ActionDecision(name=ActionName.TURN_RIGHT, parameters={"degrees": 45}),
            provider="fake_llm",
            model="fake-model",
            duration_ms=18,
        )


class InvalidActionLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        return LLMGenerationResult(
            assistant_text="Trying an invalid action.",
            action=ActionDecision(name=ActionName.TURN_RIGHT, parameters={"degrees": "bad"}),
            provider="fake_llm",
            model="fake-model",
            duration_ms=18,
        )


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
    simulator = LowFidelitySimulator()
    execution_service = ExecutionService(simulator)
    orchestrator = Orchestrator(
        llm_provider=llm_provider,
        prompt_builder=PromptBuilder(),
        history_limit=10,
    )
    client.app.state.orchestrator = orchestrator
    client.app.state.simulator = simulator
    client.app.state.execution_service = execution_service
    client.app.state.tts_service = TTSService(
        session_manager=client.app.state.session_manager,
        tts_provider=SilentTTSProvider(),
        audio_store=client.app.state.audio_store,
    )
    client.app.state.session_runtime.set_orchestrator(orchestrator)
    client.app.state.session_runtime.set_execution_service(execution_service)
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


def test_action_decision_triggers_execution_and_state_feedback() -> None:
    with TestClient(app) as client:
        install_runtime(client, FakeLLMProvider())
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
            action_decided = websocket.receive_json()
            execution_started = websocket.receive_json()
            execution_completed = websocket.receive_json()
            state_updated = websocket.receive_json()

            websocket.send_json({"type": "session.request_state", "payload": {}})
            state_event = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert transcription_completed["type"] == "transcription.completed"
    assert action_decided == {
        "type": "action.decided",
        "session_id": session_id,
        "timestamp": action_decided["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "action": {
                "name": "turn_right",
                "parameters": {"degrees": 45},
            },
        },
    }
    assert execution_started == {
        "type": "action.execution_started",
        "session_id": session_id,
        "timestamp": execution_started["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "action": {
                "name": "turn_right",
                "parameters": {"degrees": 45},
            },
        },
    }
    assert execution_completed["type"] == "action.execution_completed"
    assert execution_completed["payload"] == {
        "session_id": session_id,
        "request_id": transcription_completed["payload"]["request_id"],
        "success": True,
        "action": {
            "name": "turn_right",
            "parameters": {"degrees": 45},
        },
        "duration_ms": execution_completed["payload"]["duration_ms"],
    }
    assert state_updated["type"] == "simulator.state_updated"
    assert state_updated["payload"]["session_id"] == session_id
    assert state_updated["payload"]["state"]["heading_deg"] == 45.0
    assert state_updated["payload"]["state"]["velocity"] == 0.0
    assert state_updated["payload"]["state"]["is_moving"] is False
    assert state_updated["payload"]["state"]["last_action"] == "turn_right"
    assert state_event["type"] == "session.state"
    assert state_event["payload"]["simulator_state"]["heading_deg"] == 45.0
    assert state_event["payload"]["simulator_state"]["last_action"] == "turn_right"


def test_invalid_actions_emit_execution_failure_and_error() -> None:
    with TestClient(app) as client:
        install_runtime(client, InvalidActionLLMProvider())
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
            action_decided = websocket.receive_json()
            execution_started = websocket.receive_json()
            execution_completed = websocket.receive_json()
            error_event = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert transcription_completed["type"] == "transcription.completed"
    assert action_decided["type"] == "action.decided"
    assert execution_started["type"] == "action.execution_started"
    assert execution_completed == {
        "type": "action.execution_completed",
        "session_id": session_id,
        "timestamp": execution_completed["timestamp"],
        "payload": {
            "session_id": session_id,
            "request_id": transcription_completed["payload"]["request_id"],
            "success": False,
            "action": {
                "name": "turn_right",
                "parameters": {"degrees": "bad"},
            },
            "duration_ms": 0,
        },
    }
    assert error_event == {
        "type": "error",
        "session_id": session_id,
        "timestamp": error_event["timestamp"],
        "payload": {
            "code": "invalid_action_parameters",
            "message": "Invalid value for degrees: bad",
        },
    }
