from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.transcription import TranscriptionResult
from app.services.live_audio_service import LiveAudioService
from app.services.stt.base import SpeechToTextAdapter
from app.services.utterance_queue import UtteranceQueue


class FakeSTTAdapter(SpeechToTextAdapter):
    async def transcribe_file(self, audio_path):  # type: ignore[override]
        return TranscriptionResult(
            text="hello world",
            language="en",
            duration_ms=120,
            provider="fake_stt",
        )


def install_live_audio_service(
    client: TestClient,
    adapter: SpeechToTextAdapter | None = None,
) -> LiveAudioService:
    settings = client.app.state.settings
    session_manager = client.app.state.session_manager
    session_runtime = client.app.state.session_runtime
    session_runtime.set_orchestrator(None)

    service_ref: dict[str, LiveAudioService] = {}

    async def processor(item):
        await service_ref["value"].process_utterance(item)

    async def on_idle(session_id):
        await service_ref["value"].on_session_idle(session_id)

    queue = UtteranceQueue(
        processor=processor,
        max_depth_per_session=settings.live_audio_max_queue_per_session,
        on_session_idle=on_idle,
    )
    service = LiveAudioService(
        settings=settings,
        session_manager=session_manager,
        session_runtime=session_runtime,
        stt_adapter=adapter or FakeSTTAdapter(),
        utterance_queue=queue,
    )
    service_ref["value"] = service
    client.app.state.live_audio_service = service
    client.app.state.utterance_queue = queue
    return service


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["session_id"]


def test_live_audio_config_exposed_via_demo_context() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/context")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert "live_audio" in payload
    live_audio = payload["live_audio"]
    assert live_audio["enabled"] is True
    assert live_audio["max_seconds_per_utterance"] > 0
    assert live_audio["max_queue_per_session"] >= 1
    assert "/sessions/{session_id}/live-audio" in live_audio["submit_path"]


def test_live_audio_start_and_stop_controls() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        session_id = create_session(client)

        start = client.post(f"/api/v1/sessions/{session_id}/live-audio/start")
        stop = client.post(f"/api/v1/sessions/{session_id}/live-audio/stop")

    assert start.status_code == status.HTTP_200_OK
    assert start.json() == {"session_id": session_id, "state": "started"}
    assert stop.status_code == status.HTTP_200_OK
    assert stop.json() == {"session_id": session_id, "state": "stopped"}


def test_live_audio_start_rejects_unknown_session() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        response = client.post(f"/api/v1/sessions/{uuid4()}/live-audio/start")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "code": "session_not_found",
        "message": "Session not found",
    }


def test_live_audio_submit_returns_accepted() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/live-audio",
            data={"duration_ms": "900"},
            files={"file": ("utterance.webm", BytesIO(b"\x1a" * 64), "audio/webm")},
        )

    assert response.status_code == status.HTTP_202_ACCEPTED
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["duration_ms"] == 900
    assert payload["queued_position"] >= 1
    assert "request_id" in payload


def test_live_audio_submit_rejects_empty_upload() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/live-audio",
            data={"duration_ms": "700"},
            files={"file": ("utterance.webm", BytesIO(b""), "audio/webm")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "empty_upload"


def test_live_audio_submit_rejects_duration_too_long() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/live-audio",
            data={"duration_ms": "600000"},
            files={"file": ("utterance.webm", BytesIO(b"\x00" * 32), "audio/webm")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "utterance_too_long"


def test_live_audio_submit_rejects_invalid_content_type() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)
        session_id = create_session(client)

        response = client.post(
            f"/api/v1/sessions/{session_id}/live-audio",
            data={"duration_ms": "900"},
            files={"file": ("utterance.txt", BytesIO(b"text"), "text/plain")},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid_audio_type"


def test_live_audio_submit_rejects_unknown_session() -> None:
    with TestClient(app) as client:
        install_live_audio_service(client)

        response = client.post(
            f"/api/v1/sessions/{uuid4()}/live-audio",
            data={"duration_ms": "800"},
            files={"file": ("utterance.webm", BytesIO(b"\x00" * 32), "audio/webm")},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "session_not_found"
