from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.action import ActionDecision, ActionName


class SimulatorState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading_deg: float = Field(ge=0, lt=360)
    velocity: float = Field(ge=0)
    is_moving: bool
    last_action: ActionName | None = None
    updated_at: datetime


class ActionExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionDecision
    success: bool
    state: SimulatorState
    duration_ms: int = Field(ge=0)
