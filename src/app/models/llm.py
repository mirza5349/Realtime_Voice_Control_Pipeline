from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.action import ActionDecision


class ConversationRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ConversationRole
    content: str


class LLMGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    request_id: UUID
    messages: list[ConversationMessage]


class LLMStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_text: str
    action: ActionDecision


class LLMGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_text: str
    action: ActionDecision
    provider: str
    model: str
    duration_ms: int = Field(ge=0)
