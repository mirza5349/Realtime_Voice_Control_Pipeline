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
from app.services.execution_service import ExecutionService
from app.services.llm.base import LLMProvider
from app.services.orchestrator import Orchestrator
from app.services.prompt_builder import PromptBuilder
from app.services.simulator.low_fidelity import LowFidelitySimulator
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


def install_runtime(client: TestClient, tmp_path: Path, tts_provider: TextToSpeechProvider) -> None:
    orchestrator = Orchestrator(
        llm_provider=FakeLLMProvider(),
        prompt_builder=PromptBuilder(),
        history_limit=10,
    )
    simulator = LowFidelitySimulator()
    execution_service = ExecutionService(simulator)
    audio_store = AudioStore(tmp_path / "audio", "/api/v1/audio", 3600)
    tts_service = TTSService(
        session_manager=client.app.state.session_manager,
        tts_provider=tts_provider,
        audio_store=audio_store,
    )
    client.app.state.audio_store = audio_store
    client.app.state.orchestrator = orchestrator
    client.app.state.execution_service = execution_service
    client.app.state.tts_service = tts_service
    client.app.state.diagnostics_service.set_execution_service(execution_service)
    client.app.state.session_runtime.set_orchestrator(orchestrator)
    client.app.state.session_runtime.set_execution_service(execution_service)
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


def run_request(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
        websocket.receive_json()
        response = client.post(
            f"/api/v1/sessions/{session_id}/transcriptions",
            files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
        )
        assert response.status_code == status.HTTP_200_OK

        while True:
            event = websocket.receive_json()
            if event["type"] == "simulator.state_updated":
                break
            if (
                event["type"] == "action.execution_completed"
                and event["payload"]["success"] is False
            ):
                websocket.receive_json()
                break


def test_metrics_summary_returns_aggregated_request_and_latency_data(tmp_path: Path) -> None:
    with TestClient(app) as client:
        install_runtime(client, tmp_path / "success", FakeTTSProvider())
        success_session_id = create_session(client)
        run_request(client, success_session_id)

        install_runtime(client, tmp_path / "failure", FailingTTSProvider())
        failure_session_id = create_session(client)
        run_request(client, failure_session_id)

        summary_response = client.get("/api/v1/metrics/summary")

    assert summary_response.status_code == status.HTTP_200_OK
    assert summary_response.json() == {
        "active_sessions": 0,
        "active_websockets": 0,
        "completed_requests": 1,
        "failed_requests": 1,
        "recent_error_count": 1,
        "avg_transcription_duration_ms": 42.0,
        "avg_llm_duration_ms": 18.0,
        "avg_execution_duration_ms": 0.0,
        "avg_tts_duration_ms": 210.0,
        "avg_end_to_end_duration_ms": summary_response.json()["avg_end_to_end_duration_ms"],
    }
    assert summary_response.json()["avg_end_to_end_duration_ms"] is not None
