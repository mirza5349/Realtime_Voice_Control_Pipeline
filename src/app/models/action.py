from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionName(str, Enum):
    NONE = "none"
    MOVE_FORWARD = "move_forward"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    STOP = "stop"
    STATUS_REPORT = "status_report"


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ActionName = ActionName.NONE
    parameters: dict[str, Any] = Field(default_factory=dict)

    def resolved_name(self) -> ActionName:
        return ActionName(self.name)
