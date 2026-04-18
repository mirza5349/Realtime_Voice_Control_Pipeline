from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from app.models.transcription import TranscriptionResult
from app.services.stt.base import (
    SpeechToTextAdapter,
    STTConfigurationError,
    STTExecutionError,
)


class WhisperCppSpeechToTextAdapter(SpeechToTextAdapter):
    def __init__(
        self,
        binary_path: str | None,
        model_path: str | None,
        threads: int,
        language: str | None,
    ) -> None:
        self._binary_path = binary_path or "whisper-cli"
        self._model_path = model_path
        self._threads = threads
        self._language = language or None

    async def transcribe_file(self, audio_path: Path) -> TranscriptionResult:
        return await asyncio.to_thread(self._run_transcription, audio_path)

    def _run_transcription(self, audio_path: Path) -> TranscriptionResult:
        if not self._model_path:
            raise STTConfigurationError("WHISPER_CPP_MODEL_PATH is required for transcription")

        start = perf_counter()

        with TemporaryDirectory() as output_dir:
            output_prefix = Path(output_dir) / "transcription"
            prepared_audio = self._prepare_audio(audio_path, Path(output_dir))
            command = [
                self._binary_path,
                "-m",
                self._model_path,
                "-f",
                str(prepared_audio),
                "-otxt",
                "-of",
                str(output_prefix),
            ]

            if self._threads > 0:
                command.extend(["-t", str(self._threads)])
            if self._language:
                command.extend(["-l", self._language])

            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError as error:
                raise STTConfigurationError(
                    f"whisper.cpp binary not found: {self._binary_path}"
                ) from error
            except OSError as error:
                raise STTExecutionError(str(error)) from error

            if completed.returncode != 0:
                message = (
                    completed.stderr.strip() or completed.stdout.strip() or "whisper.cpp failed"
                )
                raise STTExecutionError(message)

            transcript_path = output_prefix.with_suffix(".txt")
            text = (
                transcript_path.read_text(encoding="utf-8").strip()
                if transcript_path.exists()
                else ""
            )

            if not text:
                text = completed.stdout.strip()

            duration_ms = int((perf_counter() - start) * 1000)
            return TranscriptionResult(
                text=text,
                language=self._language,
                duration_ms=duration_ms,
                provider="whisper_cpp",
            )

    def _prepare_audio(self, audio_path: Path, work_dir: Path) -> Path:
        suffix = audio_path.suffix.lower()
        if suffix in {".wav", ".flac", ".mp3", ".ogg", ".oga"}:
            return audio_path

        converted = work_dir / "input.wav"
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            str(converted),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise STTConfigurationError(
                "ffmpeg is required to transcode browser audio before whisper.cpp"
            ) from error
        except OSError as error:
            raise STTExecutionError(str(error)) from error

        if completed.returncode != 0 or not converted.exists():
            message = completed.stderr.strip() or "ffmpeg transcode failed"
            raise STTExecutionError(message)
        return converted
