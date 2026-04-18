from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    filename: str
    content_type: str | None = None


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    language: str | None = None
    duration_ms: int = Field(ge=0)
    provider: str


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    request_id: UUID
    text: str
    language: str | None = None
    duration_ms: int = Field(ge=0)
    provider: str


class TranscriptionErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
