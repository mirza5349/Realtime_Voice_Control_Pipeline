from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SessionStatus(str, Enum):
    INITIALIZED = "initialized"
    ACTIVE = "active"


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Session(BaseModel):
    session_id: UUID
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
