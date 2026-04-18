from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AudioAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    session_id: UUID
    request_id: UUID
    content_type: str
    url: str
    duration_ms: int | None = Field(default=None, ge=0)
    size_bytes: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime


class StoredAudioAsset(AudioAsset):
    file_path: Path
    filename: str


class AudioAssetErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
