from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from app.models.audio import StoredAudioAsset


class AudioStore:
    def __init__(self, storage_dir: str | Path, public_base_path: str, ttl_seconds: int) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._public_base_path = public_base_path.rstrip("/") or "/"
        self._ttl = timedelta(seconds=ttl_seconds)
        self._assets: dict[UUID, StoredAudioAsset] = {}
        self._lock = Lock()

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    def initialize(self) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        with self._lock:
            expired_ids = [
                asset_id for asset_id, asset in self._assets.items() if asset.expires_at <= now
            ]
            for asset_id in expired_ids:
                asset = self._assets.pop(asset_id)
                asset.file_path.unlink(missing_ok=True)
            return len(expired_ids)

    def purge_all(self) -> None:
        with self._lock:
            for asset in list(self._assets.values()):
                asset.file_path.unlink(missing_ok=True)
            self._assets.clear()
            if self._storage_dir.exists():
                for leftover in self._storage_dir.iterdir():
                    if leftover.is_file():
                        leftover.unlink(missing_ok=True)

    def store_file(
        self,
        session_id: UUID,
        request_id: UUID,
        source_path: Path,
        content_type: str,
        duration_ms: int | None,
    ) -> StoredAudioAsset:
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + self._ttl
        asset_id = uuid4()
        suffix = source_path.suffix or ".bin"
        filename = f"{asset_id}{suffix}"
        destination = self._storage_dir / filename

        with self._lock:
            self._cleanup_expired_locked(created_at)
            shutil.move(str(source_path), str(destination))
            asset = StoredAudioAsset(
                asset_id=asset_id,
                session_id=session_id,
                request_id=request_id,
                content_type=content_type,
                url=f"{self._public_base_path}/{asset_id}",
                duration_ms=duration_ms,
                size_bytes=destination.stat().st_size,
                created_at=created_at,
                expires_at=expires_at,
                file_path=destination,
                filename=filename,
            )
            self._assets[asset_id] = asset
            return asset.model_copy(deep=True)

    def get_asset(self, asset_id: UUID) -> StoredAudioAsset | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._cleanup_expired_locked(now)
            asset = self._assets.get(asset_id)
            if asset is None:
                return None
            if not asset.file_path.exists():
                self._assets.pop(asset_id, None)
                return None
            return asset.model_copy(deep=True)

    def _cleanup_expired_locked(self, now: datetime) -> None:
        expired_ids = [
            asset_id for asset_id, asset in self._assets.items() if asset.expires_at <= now
        ]
        for asset_id in expired_ids:
            asset = self._assets.pop(asset_id)
            asset.file_path.unlink(missing_ok=True)
