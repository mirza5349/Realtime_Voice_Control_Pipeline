from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["session_id"]


def test_websocket_connect_and_message_flow() -> None:
    with TestClient(app) as client:
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            connected_event = websocket.receive_json()

            assert connected_event["type"] == "session.connected"
            assert connected_event["session_id"] == session_id
            assert connected_event["payload"] == {"session_status": "active"}
            assert "timestamp" in connected_event

            websocket.send_json({"type": "client.ping", "payload": {"message": "hello"}})
            pong_event = websocket.receive_json()

            assert pong_event["type"] == "server.pong"
            assert pong_event["session_id"] == session_id
            assert pong_event["payload"] == {"message": "hello"}
            assert "timestamp" in pong_event

            websocket.send_json({"type": "session.request_state", "payload": {}})
            state_event = websocket.receive_json()

            assert state_event["type"] == "session.state"
            assert state_event["session_id"] == session_id
            assert state_event["payload"]["session_id"] == session_id
            assert state_event["payload"]["status"] == "active"
            assert state_event["payload"]["simulator_state"] == {
                "heading_deg": 0.0,
                "velocity": 0.0,
                "is_moving": False,
                "last_action": None,
                "updated_at": state_event["payload"]["simulator_state"]["updated_at"],
            }
            assert "timestamp" in state_event


def test_unknown_session_websocket_is_rejected() -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/api/v1/ws/sessions/{uuid4()}"):
                pass

    assert error.value.code == status.WS_1008_POLICY_VIOLATION


def test_malformed_message_returns_error_and_connection_stays_alive() -> None:
    with TestClient(app) as client:
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as websocket:
            websocket.receive_json()

            websocket.send_text("not-json")
            error_event = websocket.receive_json()

            assert error_event["type"] == "error"
            assert error_event["session_id"] == session_id
            assert error_event["payload"] == {
                "code": "invalid_json",
                "message": "Message must be valid JSON",
            }

            websocket.send_json({"type": "session.request_state", "payload": {}})
            state_event = websocket.receive_json()

            assert state_event["type"] == "session.state"
            assert state_event["payload"]["status"] == "active"
            assert state_event["payload"]["simulator_state"]["heading_deg"] == 0.0


def test_single_active_connection_and_disconnect_cleanup() -> None:
    with TestClient(app) as client:
        session_id = create_session(client)

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as first_websocket:
            first_websocket.receive_json()

            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}"):
                    pass

            assert error.value.code == status.WS_1008_POLICY_VIOLATION

        with client.websocket_connect(f"/api/v1/ws/sessions/{session_id}") as second_websocket:
            connected_event = second_websocket.receive_json()

        assert connected_event["type"] == "session.connected"
        assert connected_event["payload"] == {"session_status": "active"}
