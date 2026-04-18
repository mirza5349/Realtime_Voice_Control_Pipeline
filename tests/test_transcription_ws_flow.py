from io import BytesIO

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.transcription import TranscriptionResult
from app.services.stt.base import SpeechToTextAdapter, STTAdapterError
from app.services.transcription_service import TranscriptionService


class FakeSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text="hello world",
            language="en",
            duration_ms=42,
            provider="fake_stt",
        )


class FailingSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        raise STTAdapterError("adapter failed")


def install_transcription_service(client: TestClient, adapter: SpeechToTextAdapter) -> None:
    client.app.state.session_runtime.set_orchestrator(None)
    client.app.state.orchestrator = None
    client.app.state.transcription_service = TranscriptionService(
        session_manager=client.app.state.session_manager,
        session_runtime=client.app.state.session_runtime,
        stt_adapter=adapter,
        upload_max_bytes=1024 * 1024,
    )


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["session_id"]


def test_transcription_events_are_emitted_to_websocket_session() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FakeSpeechToTextAdapter())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            started_event = websocket.receive_json()
            completed_event = websocket.receive_json()

    assert response.status_code == status.HTTP_200_OK
    assert started_event["type"] == "transcription.started"
    assert started_event["session_id"] == session_id
    assert started_event["payload"]["session_id"] == session_id
    assert "request_id" in started_event["payload"]
    assert completed_event["type"] == "transcription.completed"
    assert completed_event["session_id"] == session_id
    assert completed_event["payload"] == {
        "session_id": session_id,
        "request_id": started_event["payload"]["request_id"],
        "text": "hello world",
        "language": "en",
        "duration_ms": 42,
    }


def test_transcription_failure_emits_error_event() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FailingSpeechToTextAdapter())
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            response = client.post(
                f"/api/v1/sessions/{session_id}/transcriptions",
                files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
            )

            started_event = websocket.receive_json()
            error_event = websocket.receive_json()

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert started_event["type"] == "transcription.started"
    assert error_event == {
        "type": "error",
        "session_id": session_id,
        "timestamp": error_event["timestamp"],
        "payload": {
            "code": "transcription_failed",
            "message": "adapter failed",
        },
    }
