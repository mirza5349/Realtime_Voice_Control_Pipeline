from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.tts import SynthesizedAudio, TTSRequest


class TTSProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TTSConfigurationError(TTSProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("tts_configuration_error", message)


class TTSExecutionError(TTSProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("tts_execution_failed", message)


class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(self, request: TTSRequest, output_path: Path) -> SynthesizedAudio:
        raise NotImplementedError
