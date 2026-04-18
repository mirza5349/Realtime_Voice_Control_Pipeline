from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import create_api_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.audio_store import AudioStore
from app.services.connection_manager import ConnectionManager
from app.services.demo_service import DemoService, validate_providers
from app.services.diagnostics_service import DiagnosticsService
from app.services.execution_service import ExecutionService
from app.services.live_audio_service import LiveAudioService
from app.services.llm.ollama import OllamaLLMProvider
from app.services.metrics_collector import MetricsCollector
from app.services.orchestrator import Orchestrator
from app.services.prompt_builder import PromptBuilder
from app.services.session_manager import SessionManager
from app.services.session_runtime import SessionRuntime
from app.services.simulator.low_fidelity import LowFidelitySimulator
from app.services.stt.whisper_cpp import WhisperCppSpeechToTextAdapter
from app.services.transcription_service import TranscriptionService
from app.services.tts.piper import PiperTextToSpeechProvider
from app.services.tts_service import TTSService
from app.services.utterance_queue import UtteranceQueue

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.app_log_level)

    if settings.stt_provider != "whisper_cpp":
        raise ValueError(f"Unsupported STT provider: {settings.stt_provider}")
    if settings.llm_provider != "ollama":
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
    if settings.tts_provider != "piper":
        raise ValueError(f"Unsupported TTS provider: {settings.tts_provider}")

    _initialize_storage_dirs(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        session_manager = SessionManager()
        connection_manager = ConnectionManager()
        metrics_collector = MetricsCollector(
            trace_history_limit=settings.trace_history_limit,
            retention_limit=settings.metrics_retention_limit,
        )
        audio_store = AudioStore(
            storage_dir=settings.audio_storage_dir,
            public_base_path=settings.audio_public_base_path,
            ttl_seconds=settings.audio_file_ttl_seconds,
        )
        audio_store.initialize()
        llm_provider = OllamaLLMProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )
        orchestrator = Orchestrator(
            llm_provider=llm_provider,
            prompt_builder=PromptBuilder(),
            history_limit=settings.session_history_limit,
        )
        simulator = LowFidelitySimulator()
        execution_service = ExecutionService(simulator)
        stt_adapter = WhisperCppSpeechToTextAdapter(
            binary_path=settings.whisper_cpp_binary_path,
            model_path=settings.whisper_cpp_model_path,
            threads=settings.whisper_cpp_threads,
            language=settings.whisper_cpp_language,
        )
        tts_provider = PiperTextToSpeechProvider(
            binary_path=settings.piper_binary_path,
            model_path=settings.piper_model_path,
        )
        tts_service = TTSService(
            session_manager=session_manager,
            tts_provider=tts_provider,
            audio_store=audio_store,
        )
        session_runtime = SessionRuntime(
            session_manager=session_manager,
            connection_manager=connection_manager,
            orchestrator=orchestrator,
            execution_service=execution_service,
            tts_service=tts_service,
            metrics_collector=metrics_collector,
        )
        diagnostics_service = DiagnosticsService(
            session_manager=session_manager,
            connection_manager=connection_manager,
            metrics_collector=metrics_collector,
            execution_service=execution_service,
        )
        live_audio_queue_ref: dict[str, UtteranceQueue] = {}
        live_audio_service_ref: dict[str, LiveAudioService] = {}

        async def _process_live_utterance(item):
            service = live_audio_service_ref["value"]
            await service.process_utterance(item)

        async def _live_session_idle(session_id):
            service = live_audio_service_ref["value"]
            await service.on_session_idle(session_id)

        utterance_queue = UtteranceQueue(
            processor=_process_live_utterance,
            max_depth_per_session=settings.live_audio_max_queue_per_session,
            on_session_idle=_live_session_idle,
        )
        live_audio_queue_ref["value"] = utterance_queue
        live_audio_service = LiveAudioService(
            settings=settings,
            session_manager=session_manager,
            session_runtime=session_runtime,
            stt_adapter=stt_adapter,
            utterance_queue=utterance_queue,
        )
        live_audio_service_ref["value"] = live_audio_service
        demo_service = DemoService(
            settings=settings,
            diagnostics_service=diagnostics_service,
            live_audio_service=live_audio_service,
            samples_dir=Path(settings.demo_samples_dir),
            samples_url_prefix=settings.demo_samples_public_path,
        )
        app.state.session_manager = session_manager
        app.state.connection_manager = connection_manager
        app.state.metrics_collector = metrics_collector
        app.state.diagnostics_service = diagnostics_service
        app.state.demo_service = demo_service
        app.state.live_audio_service = live_audio_service
        app.state.utterance_queue = utterance_queue
        app.state.audio_store = audio_store
        app.state.llm_provider = llm_provider
        app.state.orchestrator = orchestrator
        app.state.simulator = simulator
        app.state.execution_service = execution_service
        app.state.session_runtime = session_runtime
        app.state.stt_adapter = stt_adapter
        app.state.tts_provider = tts_provider
        app.state.tts_service = tts_service
        app.state.transcription_service = TranscriptionService(
            session_manager=session_manager,
            session_runtime=session_runtime,
            stt_adapter=stt_adapter,
            upload_max_bytes=settings.upload_max_bytes,
        )

        if settings.demo_startup_validate_providers:
            validate_providers(demo_service)

        cleanup_task: asyncio.Task[None] | None = None
        if settings.demo_auto_cleanup_audio:
            cleanup_task = asyncio.create_task(
                _run_audio_cleanup_loop(audio_store, settings.demo_cleanup_interval_seconds)
            )

        logger.info("event=startup service=%s environment=%s", settings.app_name, settings.app_env)
        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
            await utterance_queue.shutdown()
            logger.info(
                "event=shutdown service=%s environment=%s", settings.app_name, settings.app_env
            )

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(create_api_router(settings))
    _mount_demo_ui(app)
    return app


def _initialize_storage_dirs(settings: Settings) -> None:
    Path(settings.audio_storage_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.demo_samples_dir).mkdir(parents=True, exist_ok=True)


async def _run_audio_cleanup_loop(audio_store: AudioStore, interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removed = await asyncio.to_thread(audio_store.cleanup_expired)
            if removed:
                logger.info("event=audio_cleanup removed=%d", removed)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("event=audio_cleanup_error detail=%s", error)


def _mount_demo_ui(app: FastAPI) -> None:
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    demo_html_path = TEMPLATES_DIR / "demo.html"

    @app.get("/", include_in_schema=False, response_model=None)
    def get_root() -> RedirectResponse:
        return RedirectResponse(url="/demo", status_code=307)

    @app.get("/demo", include_in_schema=False, response_model=None)
    def get_demo_page() -> HTMLResponse | JSONResponse:
        if not demo_html_path.exists():
            return JSONResponse(
                status_code=500,
                content={
                    "code": "demo_template_missing",
                    "message": "Demo template is not installed",
                },
            )
        return HTMLResponse(demo_html_path.read_text(encoding="utf-8"))


app = create_app()
