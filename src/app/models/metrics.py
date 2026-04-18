from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.session import SessionStatus
from app.models.simulator import SimulatorState


class MetricsErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RuntimeErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    timestamp: datetime
    request_id: UUID | None = None


class StageTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class RequestTraceStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RequestStageTimings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcription: StageTiming | None = None
    llm: StageTiming | None = None
    execution: StageTiming | None = None
    tts: StageTiming | None = None


class RequestTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    status: RequestTraceStatus
    transcription_duration_ms: int | None = Field(default=None, ge=0)
    llm_duration_ms: int | None = Field(default=None, ge=0)
    execution_duration_ms: int | None = Field(default=None, ge=0)
    tts_duration_ms: int | None = Field(default=None, ge=0)
    end_to_end_duration_ms: int | None = Field(default=None, ge=0)
    stage_timings: RequestStageTimings
    last_error: RuntimeErrorInfo | None = None


class SessionDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    session_status: SessionStatus
    active_connection: bool
    current_simulator_state: SimulatorState | None = None
    recent_requests: list[RequestTrace]
    last_error: RuntimeErrorInfo | None = None
    created_at: datetime
    updated_at: datetime


class MetricsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_sessions: int = Field(ge=0)
    active_websockets: int = Field(ge=0)
    completed_requests: int = Field(ge=0)
    failed_requests: int = Field(ge=0)
    recent_error_count: int = Field(ge=0)
    avg_transcription_duration_ms: float | None = Field(default=None, ge=0)
    avg_llm_duration_ms: float | None = Field(default=None, ge=0)
    avg_execution_duration_ms: float | None = Field(default=None, ge=0)
    avg_tts_duration_ms: float | None = Field(default=None, ge=0)
    avg_end_to_end_duration_ms: float | None = Field(default=None, ge=0)
