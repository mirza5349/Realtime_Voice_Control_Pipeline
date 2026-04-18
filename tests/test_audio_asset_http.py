import wave
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.services.audio_store import AudioStore


def write_wav(path: Path, duration_ms: int) -> None:
    frames = max(1, int(22050 * duration_ms / 1000))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * frames)


def test_audio_asset_route_returns_stored_file(tmp_path: Path) -> None:
    with TestClient(app) as client:
        audio_store = AudioStore(tmp_path / "audio", "/api/v1/audio", 3600)
        client.app.state.audio_store = audio_store
        session_id = client.post("/api/v1/sessions", json={}).json()["session_id"]

        with NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_path = Path(temp_file.name)

        try:
            write_wav(temp_path, 120)
            asset = audio_store.store_file(
                session_id=session_id,
                request_id=uuid4(),
                source_path=temp_path,
                content_type="audio/wav",
                duration_ms=120,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        response = client.get(f"/api/v1/audio/{asset.asset_id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) > 0


def test_audio_asset_route_returns_typed_not_found_error() -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/v1/audio/{uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "code": "audio_asset_not_found",
        "message": "Audio asset not found",
    }
