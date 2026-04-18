from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    request_id: UUID
    text: str = Field(min_length=1)


class SynthesizedAudio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    voice: str
    content_type: str
    duration_ms: int | None = Field(default=None, ge=0)
    file_path: Path
