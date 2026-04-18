from io import BytesIO
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.transcription import TranscriptionResult
from app.services.stt.base import SpeechToTextAdapter, STTAdapterError
from app.services.transcription_service import TranscriptionService


class FakeSpeechToTextAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text=f"transcript:{audio_path.suffix}",
            language="en",
            duration_ms=123,
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


def test_transcription_upload_returns_typed_response() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FakeSpeechToTextAdapter())
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/transcriptions",
            files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["text"] == "transcript:.wav"
    assert payload["language"] == "en"
    assert payload["duration_ms"] == 123
    assert payload["provider"] == "fake_stt"
    assert "request_id" in payload


def test_transcription_upload_rejects_unknown_session() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FakeSpeechToTextAdapter())

        response = client.post(
            f"/api/v1/sessions/{uuid4()}/transcriptions",
            files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "code": "session_not_found",
        "message": "Session not found",
    }


def test_transcription_upload_rejects_invalid_audio_type() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FakeSpeechToTextAdapter())
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/transcriptions",
            files={"file": ("sample.txt", BytesIO(b"audio"), "text/plain")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "code": "invalid_audio_type",
        "message": "Unsupported audio upload",
    }


def test_transcription_adapter_failure_returns_typed_error() -> None:
    with TestClient(app) as client:
        install_transcription_service(client, FailingSpeechToTextAdapter())
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/transcriptions",
            files={"file": ("sample.wav", BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert response.json() == {
        "code": "transcription_failed",
        "message": "adapter failed",
    }
