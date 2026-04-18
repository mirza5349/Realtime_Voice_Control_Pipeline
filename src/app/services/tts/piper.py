from __future__ import annotations

import asyncio
import subprocess
import wave
from pathlib import Path

from app.models.tts import SynthesizedAudio, TTSRequest
from app.services.tts.base import (
    TextToSpeechProvider,
    TTSConfigurationError,
    TTSExecutionError,
)


class PiperTextToSpeechProvider(TextToSpeechProvider):
    def __init__(self, binary_path: str | None, model_path: str | None) -> None:
        self._binary_path = binary_path or "piper"
        self._model_path = model_path

    async def synthesize(self, request: TTSRequest, output_path: Path) -> SynthesizedAudio:
        return await asyncio.to_thread(self._run_synthesis, request, output_path)

    def _run_synthesis(self, request: TTSRequest, output_path: Path) -> SynthesizedAudio:
        if not self._model_path:
            raise TTSConfigurationError("PIPER_MODEL_PATH is required for speech synthesis")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._binary_path,
            "--model",
            self._model_path,
            "--output_file",
            str(output_path),
        ]

        try:
            completed = subprocess.run(
                command,
                input=request.text,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise TTSConfigurationError(f"Piper binary not found: {self._binary_path}") from error
        except OSError as error:
            raise TTSExecutionError(str(error)) from error

        if completed.returncode != 0:
            message = (
                completed.stderr.strip() or completed.stdout.strip() or "Piper synthesis failed"
            )
            raise TTSExecutionError(message)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSExecutionError("Piper did not produce an audio file")

        return SynthesizedAudio(
            provider="piper",
            voice=Path(self._model_path).stem,
            content_type="audio/wav",
            duration_ms=_read_wav_duration_ms(output_path),
            file_path=output_path,
        )


def _read_wav_duration_ms(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            frames = wav_file.getnframes()
            return int(frames * 1000 / frame_rate)
    except (OSError, wave.Error):
        return None
