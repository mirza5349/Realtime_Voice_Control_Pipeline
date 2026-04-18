from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "local-voice-ai-pipeline",
        "environment": "development",
    }


def test_session_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/api/v1/sessions" in route_paths
    assert "/api/v1/sessions/{session_id}" in route_paths
    assert "/api/v1/sessions/{session_id}/diagnostics" in route_paths
    assert "/api/v1/sessions/{session_id}/transcriptions" in route_paths
    assert "/api/v1/audio/{asset_id}" in route_paths
    assert "/api/v1/metrics/summary" in route_paths
    assert "/api/v1/ws/sessions/{session_id}" in route_paths


def test_create_and_fetch_session() -> None:
    with TestClient(app) as client:
        create_response = client.post("/api/v1/sessions", json={})

        assert create_response.status_code == 201
        create_payload = create_response.json()

        fetch_response = client.get(f"/api/v1/sessions/{create_payload['session_id']}")

    assert fetch_response.status_code == 200
    assert fetch_response.json() == create_payload
