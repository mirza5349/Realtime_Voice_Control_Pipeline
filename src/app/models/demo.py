from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.live_audio import LiveAudioConfig
from app.models.metrics import RequestTrace, RuntimeErrorInfo
from app.models.session import SessionStatus
from app.models.simulator import SimulatorState


class DemoProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str
    configured: bool
    detail: str | None = None


class DemoProvidersStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stt: DemoProviderStatus
    llm: DemoProviderStatus
    tts: DemoProviderStatus


class DemoContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    environment: str
    demo_mode: bool
    api_prefix: str
    audio_base_path: str
    sessions_path: str
    metrics_summary_path: str
    websocket_base_path: str
    demo_samples_path: str
    providers: DemoProvidersStatus
    live_audio: LiveAudioConfig


class DemoSampleAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    size_bytes: int = Field(ge=0)
    content_type: str = "audio/wav"


class DemoSampleAssetList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[DemoSampleAsset]


class DemoLatencySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    transcription_duration_ms: int | None = Field(default=None, ge=0)
    llm_duration_ms: int | None = Field(default=None, ge=0)
    execution_duration_ms: int | None = Field(default=None, ge=0)
    tts_duration_ms: int | None = Field(default=None, ge=0)
    end_to_end_duration_ms: int | None = Field(default=None, ge=0)


class DemoSessionOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    session_status: SessionStatus
    active_connection: bool
    simulator_state: SimulatorState | None = None
    latest_latency: DemoLatencySnapshot | None = None
    recent_requests: list[RequestTrace]
    last_error: RuntimeErrorInfo | None = None
    created_at: datetime
    updated_at: datetime


class DemoErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
