from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LiveAudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    max_seconds_per_utterance: float = Field(gt=0)
    min_seconds_per_utterance: float = Field(ge=0)
    max_queue_per_session: int = Field(ge=1)
    autoplay_default: bool
    silence_window_ms: int = Field(ge=0)
    submit_path: str


class LiveAudioControlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    state: Literal["started", "stopped"]


class LiveAudioSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    request_id: UUID
    duration_ms: int = Field(ge=0)
    queued_position: int = Field(ge=0)


class LiveAudioErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
