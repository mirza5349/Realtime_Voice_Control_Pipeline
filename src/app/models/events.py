from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.models.action import ActionDecision
from app.models.session import SessionStatus
from app.models.simulator import SimulatorState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientPingPayload(EventPayload):
    message: str


class SessionRequestStatePayload(EventPayload):
    pass


class SessionConnectedPayload(EventPayload):
    session_status: SessionStatus


class ServerPongPayload(EventPayload):
    message: str


class SessionStatePayload(EventPayload):
    session_id: UUID
    status: SessionStatus
    simulator_state: SimulatorState | None = None


class ErrorPayload(EventPayload):
    code: str
    message: str


class TranscriptionStartedPayload(EventPayload):
    session_id: UUID
    request_id: UUID


class TranscriptionCompletedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    text: str
    language: str | None = None
    duration_ms: int


class LLMStartedPayload(EventPayload):
    session_id: UUID
    request_id: UUID


class LLMCompletedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    duration_ms: int


class AssistantResponsePayload(EventPayload):
    session_id: UUID
    request_id: UUID
    text: str


class TTSStartedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    text_length: int = Field(ge=0)


class TTSCompletedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    asset_id: UUID
    duration_ms: int = Field(ge=0)


class AssistantAudioReadyPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    asset_id: UUID
    url: str
    content_type: str


class ActionDecidedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    action: ActionDecision


class ActionExecutionStartedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    action: ActionDecision


class ActionExecutionCompletedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    success: bool
    action: ActionDecision
    duration_ms: int


class SimulatorStateUpdatedPayload(EventPayload):
    session_id: UUID
    state: SimulatorState


class LiveAudioStartedPayload(EventPayload):
    session_id: UUID


class LiveAudioUtteranceCapturedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    duration_ms: int = Field(ge=0)


class LiveAudioProcessingStartedPayload(EventPayload):
    session_id: UUID
    request_id: UUID


class LiveAudioProcessingCompletedPayload(EventPayload):
    session_id: UUID
    request_id: UUID
    status: Literal["completed", "failed"]


class LiveAudioIdlePayload(EventPayload):
    session_id: UUID


class ClientEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    session_id: UUID | None = None
    timestamp: datetime | None = None


class ServerEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    session_id: UUID
    timestamp: datetime = Field(default_factory=utc_now)


class ClientPingEvent(ClientEventBase):
    type: Literal["client.ping"] = "client.ping"
    payload: ClientPingPayload


class SessionRequestStateEvent(ClientEventBase):
    type: Literal["session.request_state"] = "session.request_state"
    payload: SessionRequestStatePayload


class SessionConnectedEvent(ServerEventBase):
    type: Literal["session.connected"] = "session.connected"
    payload: SessionConnectedPayload


class ServerPongEvent(ServerEventBase):
    type: Literal["server.pong"] = "server.pong"
    payload: ServerPongPayload


class SessionStateEvent(ServerEventBase):
    type: Literal["session.state"] = "session.state"
    payload: SessionStatePayload


class ErrorEvent(ServerEventBase):
    type: Literal["error"] = "error"
    payload: ErrorPayload


class TranscriptionStartedEvent(ServerEventBase):
    type: Literal["transcription.started"] = "transcription.started"
    payload: TranscriptionStartedPayload


class TranscriptionCompletedEvent(ServerEventBase):
    type: Literal["transcription.completed"] = "transcription.completed"
    payload: TranscriptionCompletedPayload


class LLMStartedEvent(ServerEventBase):
    type: Literal["llm.started"] = "llm.started"
    payload: LLMStartedPayload


class LLMCompletedEvent(ServerEventBase):
    type: Literal["llm.completed"] = "llm.completed"
    payload: LLMCompletedPayload


class AssistantResponseEvent(ServerEventBase):
    type: Literal["assistant.response"] = "assistant.response"
    payload: AssistantResponsePayload


class TTSStartedEvent(ServerEventBase):
    type: Literal["tts.started"] = "tts.started"
    payload: TTSStartedPayload


class TTSCompletedEvent(ServerEventBase):
    type: Literal["tts.completed"] = "tts.completed"
    payload: TTSCompletedPayload


class AssistantAudioReadyEvent(ServerEventBase):
    type: Literal["assistant.audio_ready"] = "assistant.audio_ready"
    payload: AssistantAudioReadyPayload


class ActionDecidedEvent(ServerEventBase):
    type: Literal["action.decided"] = "action.decided"
    payload: ActionDecidedPayload


class ActionExecutionStartedEvent(ServerEventBase):
    type: Literal["action.execution_started"] = "action.execution_started"
    payload: ActionExecutionStartedPayload


class ActionExecutionCompletedEvent(ServerEventBase):
    type: Literal["action.execution_completed"] = "action.execution_completed"
    payload: ActionExecutionCompletedPayload


class SimulatorStateUpdatedEvent(ServerEventBase):
    type: Literal["simulator.state_updated"] = "simulator.state_updated"
    payload: SimulatorStateUpdatedPayload


class LiveAudioStartedEvent(ServerEventBase):
    type: Literal["live_audio.started"] = "live_audio.started"
    payload: LiveAudioStartedPayload


class LiveAudioUtteranceCapturedEvent(ServerEventBase):
    type: Literal["live_audio.utterance_captured"] = "live_audio.utterance_captured"
    payload: LiveAudioUtteranceCapturedPayload


class LiveAudioProcessingStartedEvent(ServerEventBase):
    type: Literal["live_audio.processing_started"] = "live_audio.processing_started"
    payload: LiveAudioProcessingStartedPayload


class LiveAudioProcessingCompletedEvent(ServerEventBase):
    type: Literal["live_audio.processing_completed"] = "live_audio.processing_completed"
    payload: LiveAudioProcessingCompletedPayload


class LiveAudioIdleEvent(ServerEventBase):
    type: Literal["live_audio.idle"] = "live_audio.idle"
    payload: LiveAudioIdlePayload


ClientEventModel = ClientPingEvent | SessionRequestStateEvent
ClientEvent = Annotated[ClientEventModel, Field(discriminator="type")]

_client_event_adapter = TypeAdapter(ClientEvent)


def parse_client_event(value: Any) -> ClientEventModel:
    return _client_event_adapter.validate_python(value)


def bind_client_event(event: ClientEventModel, session_id: UUID) -> ClientEventModel:
    event_session_id = event.session_id or session_id
    if event_session_id != session_id:
        raise ValueError("Message session_id must match websocket session")
    event_timestamp = event.timestamp or utc_now()
    return event.model_copy(
        update={
            "session_id": event_session_id,
            "timestamp": event_timestamp,
        }
    )
