from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.transcription import TranscriptionResult


class STTAdapterError(Exception):
    pass


class STTConfigurationError(STTAdapterError):
    pass


class STTExecutionError(STTAdapterError):
    pass


class SpeechToTextAdapter(ABC):
    @abstractmethod
    async def transcribe_file(self, audio_path: Path) -> TranscriptionResult:
        raise NotImplementedError
