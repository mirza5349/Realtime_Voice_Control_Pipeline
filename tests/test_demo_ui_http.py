from __future__ import annotations

import wave
from pathlib import Path

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


def _write_sample_wav(path: Path, duration_ms: int = 500) -> None:
    frame_rate = 16000
    frames = max(1, int(frame_rate * duration_ms / 1000))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def test_demo_page_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == status.HTTP_200_OK
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Local Voice AI Pipeline" in body
    assert "/static/demo.js" in body
    assert "/static/demo.css" in body


def test_static_assets_are_served() -> None:
    with TestClient(app) as client:
        js_response = client.get("/static/demo.js")
        css_response = client.get("/static/demo.css")

    assert js_response.status_code == status.HTTP_200_OK
    assert css_response.status_code == status.HTTP_200_OK
    assert "loadContext" in js_response.text
    assert ".panel" in css_response.text


def test_demo_context_returns_expected_structure() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/context")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["service"]
    assert payload["api_prefix"] == "/api/v1"
    assert payload["sessions_path"].endswith("/sessions")
    assert payload["websocket_base_path"].endswith("/ws/sessions")
    assert payload["demo_samples_path"].endswith("/demo/samples")
    assert payload["audio_base_path"].startswith("/api/v1/audio")
    for provider_key in ("stt", "llm", "tts"):
        provider = payload["providers"][provider_key]
        assert "configured" in provider
        assert "provider" in provider


def test_demo_samples_listing_and_download(tmp_path: Path) -> None:
    samples_dir = tmp_path / "demo_assets"
    _write_sample_wav(samples_dir / "hello.wav")

    with TestClient(app) as client:
        demo_service = client.app.state.demo_service
        original_dir = demo_service.samples_dir
        demo_service.set_samples_dir(samples_dir)
        try:
            list_response = client.get("/api/v1/demo/samples")
            assert list_response.status_code == status.HTTP_200_OK
            assets = list_response.json()["assets"]
            assert len(assets) == 1
            assert assets[0]["name"] == "hello.wav"
            assert assets[0]["url"].endswith("/hello.wav")

            download = client.get("/api/v1/demo/samples/hello.wav")
            assert download.status_code == status.HTTP_200_OK
            assert download.content.startswith(b"RIFF")

            missing = client.get("/api/v1/demo/samples/missing.wav")
            assert missing.status_code == status.HTTP_404_NOT_FOUND

            invalid = client.get("/api/v1/demo/samples/..%2Fetc%2Fpasswd")
            assert invalid.status_code in {
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_404_NOT_FOUND,
            }
        finally:
            demo_service.set_samples_dir(original_dir)


def test_demo_session_overview_for_missing_session() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/sessions/00000000-0000-0000-0000-000000000000/overview")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    payload = response.json()
    assert payload["code"] == "session_not_found"


def test_demo_session_overview_returns_summary() -> None:
    with TestClient(app) as client:
        create_response = client.post("/api/v1/sessions", json={})
        assert create_response.status_code == status.HTTP_201_CREATED
        session_id = create_response.json()["session_id"]

        overview_response = client.get(f"/api/v1/demo/sessions/{session_id}/overview")

    assert overview_response.status_code == status.HTTP_200_OK
    payload = overview_response.json()
    assert payload["session_id"] == session_id
    assert payload["session_status"] in {"initialized", "active"}
    assert payload["recent_requests"] == []
    assert payload["latest_latency"] is None
