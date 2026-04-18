from __future__ import annotations

import time
from io import BytesIO

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.transcription import TranscriptionResult
from app.services.live_audio_service import LiveAudioService
from app.services.stt.base import SpeechToTextAdapter
from app.services.utterance_queue import UtteranceQueue


class CountingSTTAdapter(SpeechToTextAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe_file(self, audio_path):  # type: ignore[override]
        self.calls += 1
        return TranscriptionResult(
            text=f"utterance-{self.calls}",
            language="en",
            duration_ms=self.calls * 10,
            provider="fake_stt",
        )


def install_live_audio(client: TestClient) -> CountingSTTAdapter:
    settings = client.app.state.settings
    session_manager = client.app.state.session_manager
    session_runtime = client.app.state.session_runtime
    session_runtime.set_orchestrator(None)

    adapter = CountingSTTAdapter()
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
        stt_adapter=adapter,
        utterance_queue=queue,
    )
    service_ref["value"] = service
    client.app.state.live_audio_service = service
    client.app.state.utterance_queue = queue
    return adapter


def wait_for_event(websocket, event_type: str, timeout_s: float = 4.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        message = websocket.receive_json()
        if message.get("type") == event_type:
            return message
    raise AssertionError(f"did not receive event {event_type} within timeout")


def drain_events(websocket, event_types: set[str], timeout_s: float = 5.0) -> dict[str, list[dict]]:
    collected: dict[str, list[dict]] = {t: [] for t in event_types}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            message = websocket.receive_json()
        except Exception:
            break
        event_type = message.get("type")
        if event_type in collected:
            collected[event_type].append(message)
            if all(len(values) for values in collected.values()):
                break
    return collected


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["session_id"]


def test_continuous_demo_flow_processes_multiple_utterances() -> None:
    with TestClient(app) as client:
        adapter = install_live_audio(client)
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            start_response = client.post(
                f"/api/v1/sessions/{session_id}/live-audio/start"
            )
            assert start_response.status_code == status.HTTP_200_OK
            started = wait_for_event(websocket, "live_audio.started")
            assert started["payload"]["session_id"] == session_id

            request_ids: list[str] = []
            for index in range(3):
                response = client.post(
                    f"/api/v1/sessions/{session_id}/live-audio",
                    data={"duration_ms": str(700 + index * 50)},
                    files={
                        "file": (
                            f"utterance-{index}.webm",
                            BytesIO(b"\x0f" * 64),
                            "audio/webm",
                        )
                    },
                )
                assert response.status_code == status.HTTP_202_ACCEPTED
                request_ids.append(response.json()["request_id"])

            seen_types: list[str] = []
            seen_completed_request_ids: list[str] = []
            saw_idle = False
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                message = websocket.receive_json()
                seen_types.append(message["type"])
                if message["type"] == "live_audio.processing_completed":
                    seen_completed_request_ids.append(
                        message["payload"]["request_id"]
                    )
                if message["type"] == "live_audio.idle":
                    saw_idle = True
                if len(seen_completed_request_ids) >= 3 and saw_idle:
                    break

        assert adapter.calls == 3
        assert seen_completed_request_ids == request_ids
        assert saw_idle
        assert seen_types.count("live_audio.processing_started") == 3
        assert seen_types.count("transcription.started") == 3
        assert seen_types.count("transcription.completed") == 3


def test_continuous_demo_flow_keeps_utterances_ordered_on_rapid_submit() -> None:
    with TestClient(app) as client:
        adapter = install_live_audio(client)
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            request_ids: list[str] = []
            for index in range(4):
                response = client.post(
                    f"/api/v1/sessions/{session_id}/live-audio",
                    data={"duration_ms": "900"},
                    files={
                        "file": (
                            f"u{index}.webm",
                            BytesIO(b"\x01" * 40),
                            "audio/webm",
                        )
                    },
                )
                assert response.status_code == status.HTTP_202_ACCEPTED
                request_ids.append(response.json()["request_id"])

            completion_order: list[str] = []
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline and len(completion_order) < 4:
                message = websocket.receive_json()
                if message["type"] == "live_audio.processing_completed":
                    completion_order.append(message["payload"]["request_id"])

        assert adapter.calls == 4
        assert completion_order == request_ids
