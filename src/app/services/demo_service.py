from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import UUID

from app.core.config import Settings
from app.models.demo import (
    DemoContext,
    DemoLatencySnapshot,
    DemoProvidersStatus,
    DemoProviderStatus,
    DemoSampleAsset,
    DemoSampleAssetList,
    DemoSessionOverview,
)
from app.models.metrics import RequestTrace, RequestTraceStatus
from app.services.diagnostics_service import DiagnosticsService, DiagnosticsServiceError
from app.services.live_audio_service import LiveAudioService

logger = logging.getLogger(__name__)

_SAMPLE_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}


class DemoServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DemoService:
    def __init__(
        self,
        settings: Settings,
        diagnostics_service: DiagnosticsService,
        live_audio_service: LiveAudioService,
        samples_dir: Path,
        samples_url_prefix: str,
    ) -> None:
        self._settings = settings
        self._diagnostics_service = diagnostics_service
        self._live_audio_service = live_audio_service
        self._samples_dir = Path(samples_dir)
        self._samples_url_prefix = samples_url_prefix.rstrip("/") or "/"

    @property
    def samples_dir(self) -> Path:
        return self._samples_dir

    def set_samples_dir(self, samples_dir: Path) -> None:
        self._samples_dir = Path(samples_dir)

    def build_context(self) -> DemoContext:
        prefix = self._settings.app_api_v1_prefix.rstrip("/")
        return DemoContext(
            service=self._settings.app_name,
            environment=self._settings.app_env,
            demo_mode=self._settings.demo_mode,
            api_prefix=prefix,
            audio_base_path=self._settings.audio_public_base_path,
            sessions_path=f"{prefix}/sessions",
            metrics_summary_path=f"{prefix}/metrics/summary",
            websocket_base_path=f"{prefix}/ws/sessions",
            demo_samples_path=f"{prefix}/demo/samples",
            providers=DemoProvidersStatus(
                stt=self._stt_status(),
                llm=self._llm_status(),
                tts=self._tts_status(),
            ),
            live_audio=self._live_audio_service.config(),
        )

    def list_sample_assets(self) -> DemoSampleAssetList:
        if not self._samples_dir.exists():
            return DemoSampleAssetList(assets=[])
        entries: list[DemoSampleAsset] = []
        for path in sorted(self._samples_dir.iterdir()):
            if not path.is_file():
                continue
            content_type = _SAMPLE_CONTENT_TYPES.get(path.suffix.lower())
            if content_type is None:
                continue
            entries.append(
                DemoSampleAsset(
                    name=path.name,
                    url=f"{self._samples_url_prefix}/{path.name}",
                    size_bytes=path.stat().st_size,
                    content_type=content_type,
                )
            )
        return DemoSampleAssetList(assets=entries)

    def resolve_sample_asset(self, name: str) -> Path:
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise DemoServiceError("invalid_sample_name", "Invalid sample asset name")
        candidate = (self._samples_dir / name).resolve()
        try:
            candidate.relative_to(self._samples_dir.resolve())
        except ValueError as error:
            raise DemoServiceError(
                "invalid_sample_name",
                "Sample asset must live inside the samples directory",
            ) from error
        if not candidate.is_file():
            raise DemoServiceError("sample_not_found", f"Sample asset '{name}' not found")
        return candidate

    async def get_session_overview(self, session_id: UUID) -> DemoSessionOverview:
        try:
            diagnostics = await self._diagnostics_service.get_session_diagnostics(session_id)
        except DiagnosticsServiceError as error:
            raise DemoServiceError(error.code, error.message) from error

        latest_latency = _extract_latency(diagnostics.recent_requests)
        return DemoSessionOverview(
            session_id=diagnostics.session_id,
            session_status=diagnostics.session_status,
            active_connection=diagnostics.active_connection,
            simulator_state=diagnostics.current_simulator_state,
            latest_latency=latest_latency,
            recent_requests=diagnostics.recent_requests,
            last_error=diagnostics.last_error,
            created_at=diagnostics.created_at,
            updated_at=diagnostics.updated_at,
        )

    def _stt_status(self) -> DemoProviderStatus:
        provider = self._settings.stt_provider
        binary = self._settings.whisper_cpp_binary_path or "whisper-cli"
        model = self._settings.whisper_cpp_model_path
        binary_available = _binary_available(binary)
        model_available = bool(model) and Path(model).exists() if model else False
        configured = binary_available and model_available
        detail = _compose_status_detail(
            binary_available=binary_available,
            binary=binary,
            model_available=model_available,
            model=model,
        )
        return DemoProviderStatus(
            name="stt",
            provider=provider,
            configured=configured,
            detail=detail,
        )

    def _llm_status(self) -> DemoProviderStatus:
        provider = self._settings.llm_provider
        detail = f"base_url={self._settings.ollama_base_url}, model={self._settings.ollama_model}"
        configured = bool(self._settings.ollama_base_url) and bool(self._settings.ollama_model)
        return DemoProviderStatus(
            name="llm",
            provider=provider,
            configured=configured,
            detail=detail,
        )

    def _tts_status(self) -> DemoProviderStatus:
        provider = self._settings.tts_provider
        binary = self._settings.piper_binary_path or "piper"
        model = self._settings.piper_model_path
        binary_available = _binary_available(binary)
        model_available = bool(model) and Path(model).exists() if model else False
        configured = binary_available and model_available
        detail = _compose_status_detail(
            binary_available=binary_available,
            binary=binary,
            model_available=model_available,
            model=model,
        )
        return DemoProviderStatus(
            name="tts",
            provider=provider,
            configured=configured,
            detail=detail,
        )


def _extract_latency(traces: list[RequestTrace]) -> DemoLatencySnapshot | None:
    for trace in traces:
        if trace.status in {RequestTraceStatus.COMPLETED, RequestTraceStatus.IN_PROGRESS}:
            return DemoLatencySnapshot(
                request_id=trace.request_id,
                transcription_duration_ms=trace.transcription_duration_ms,
                llm_duration_ms=trace.llm_duration_ms,
                execution_duration_ms=trace.execution_duration_ms,
                tts_duration_ms=trace.tts_duration_ms,
                end_to_end_duration_ms=trace.end_to_end_duration_ms,
            )
    if traces:
        trace = traces[0]
        return DemoLatencySnapshot(
            request_id=trace.request_id,
            transcription_duration_ms=trace.transcription_duration_ms,
            llm_duration_ms=trace.llm_duration_ms,
            execution_duration_ms=trace.execution_duration_ms,
            tts_duration_ms=trace.tts_duration_ms,
            end_to_end_duration_ms=trace.end_to_end_duration_ms,
        )
    return None


def _binary_available(binary: str) -> bool:
    candidate = Path(binary)
    if candidate.is_absolute() or candidate.exists():
        return candidate.is_file()
    return shutil.which(binary) is not None


def _compose_status_detail(
    binary_available: bool,
    binary: str,
    model_available: bool,
    model: str | None,
) -> str:
    binary_state = "ok" if binary_available else "missing"
    model_state = "ok" if model_available else ("missing" if model else "unset")
    return f"binary={binary} ({binary_state}), model={model or ''} ({model_state})"


def validate_providers(service: DemoService) -> list[str]:
    issues: list[str] = []
    context = service.build_context()
    for status in (context.providers.stt, context.providers.llm, context.providers.tts):
        if not status.configured:
            issues.append(f"{status.name}:{status.provider}:{status.detail or 'not configured'}")
    for issue in issues:
        logger.warning("event=startup_validation status=warning detail=%s", issue)
    return issues
