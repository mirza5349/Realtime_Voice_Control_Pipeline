from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from fastapi import WebSocket

from app.models.action import ActionDecision
from app.models.audio import AudioAsset
from app.models.events import (
    ActionDecidedEvent,
    ActionDecidedPayload,
    ActionExecutionCompletedEvent,
    ActionExecutionCompletedPayload,
    ActionExecutionStartedEvent,
    ActionExecutionStartedPayload,
    AssistantAudioReadyEvent,
    AssistantAudioReadyPayload,
    AssistantResponseEvent,
    AssistantResponsePayload,
    ClientEventModel,
    ClientPingEvent,
    LiveAudioIdleEvent,
    LiveAudioIdlePayload,
    LiveAudioProcessingCompletedEvent,
    LiveAudioProcessingCompletedPayload,
    LiveAudioProcessingStartedEvent,
    LiveAudioProcessingStartedPayload,
    LiveAudioStartedEvent,
    LiveAudioStartedPayload,
    LiveAudioUtteranceCapturedEvent,
    LiveAudioUtteranceCapturedPayload,
    LLMCompletedEvent,
    LLMCompletedPayload,
    LLMStartedEvent,
    LLMStartedPayload,
    ServerEventBase,
    ServerPongEvent,
    ServerPongPayload,
    SessionConnectedEvent,
    SessionConnectedPayload,
    SessionRequestStateEvent,
    SessionStateEvent,
    SessionStatePayload,
    SimulatorStateUpdatedEvent,
    SimulatorStateUpdatedPayload,
    TranscriptionCompletedEvent,
    TranscriptionCompletedPayload,
    TranscriptionStartedEvent,
    TranscriptionStartedPayload,
    TTSCompletedEvent,
    TTSCompletedPayload,
    TTSStartedEvent,
    TTSStartedPayload,
)
from app.models.session import Session, SessionStatus
from app.models.simulator import SimulatorState
from app.models.transcription import TranscriptionResult
from app.services.connection_manager import ConnectionManager, SessionConnectionExistsError
from app.services.event_bus import EventBus
from app.services.execution_service import ExecutionService, ExecutionServiceError
from app.services.metrics_collector import MetricsCollector
from app.services.orchestrator import Orchestrator, OrchestratorError
from app.services.session_manager import SessionManager
from app.services.tracing import TraceStage
from app.services.tts_service import TTSService, TTSServiceError


class SessionNotFoundError(Exception):
    pass


class SessionRuntimeNotReadyError(Exception):
    pass


@dataclass(slots=True)
class RuntimeSession:
    session_id: UUID
    event_bus: EventBus


class SessionRuntime:
    def __init__(
        self,
        session_manager: SessionManager,
        connection_manager: ConnectionManager,
        orchestrator: Orchestrator | None = None,
        execution_service: ExecutionService | None = None,
        tts_service: TTSService | None = None,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._connection_manager = connection_manager
        self._orchestrator = orchestrator
        self._execution_service = execution_service
        self._tts_service = tts_service
        self._metrics_collector = metrics_collector
        self._runtimes: dict[UUID, RuntimeSession] = {}
        self._lock = asyncio.Lock()

    def set_orchestrator(self, orchestrator: Orchestrator | None) -> None:
        self._orchestrator = orchestrator

    def set_execution_service(self, execution_service: ExecutionService | None) -> None:
        self._execution_service = execution_service

    def set_tts_service(self, tts_service: TTSService | None) -> None:
        self._tts_service = tts_service

    async def connect(self, session_id: UUID, websocket: WebSocket) -> Session:
        session = self._session_manager.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist")

        await self._ensure_runtime(session_id)

        try:
            await self._connection_manager.connect(session_id, websocket)
        except SessionConnectionExistsError:
            raise
        except Exception:
            await self._remove_runtime(session_id)
            raise

        updated_session = self._session_manager.update_status(session_id, SessionStatus.ACTIVE)
        if updated_session is None:
            await self._connection_manager.disconnect(session_id)
            await self._remove_runtime(session_id)
            raise SessionNotFoundError(f"Session {session_id} does not exist")

        if self._execution_service is not None:
            try:
                await self._execution_service.initialize_session(session_id)
            except ExecutionServiceError as error:
                await self.send_error(session_id, code=error.code, message=error.message)

        await self._connection_manager.send_event(
            SessionConnectedEvent(
                session_id=session_id,
                payload=SessionConnectedPayload(session_status=updated_session.status),
            )
        )
        return updated_session

    async def disconnect(self, session_id: UUID) -> None:
        await self._connection_manager.disconnect(session_id)
        await self._remove_runtime(session_id)
        self._session_manager.update_status(session_id, SessionStatus.INITIALIZED)

    async def list_active_sessions(self) -> list[UUID]:
        async with self._lock:
            return list(self._runtimes.keys())

    async def shutdown(self) -> None:
        async with self._lock:
            session_ids = list(self._runtimes.keys())
            self._runtimes.clear()
        for session_id in session_ids:
            await self._connection_manager.disconnect(session_id)
            self._session_manager.update_status(session_id, SessionStatus.INITIALIZED)

    async def publish(self, event: ClientEventModel) -> None:
        session_id = event.session_id
        if session_id is None:
            raise SessionRuntimeNotReadyError(
                "Client events must be bound to a session before publishing"
            )
        runtime = await self._get_runtime(session_id)
        if runtime is None:
            raise SessionRuntimeNotReadyError(f"Runtime for session {session_id} is not active")
        await runtime.event_bus.publish(event)

    async def send_error(
        self,
        session_id: UUID,
        code: str,
        message: str,
        request_id: UUID | None = None,
    ) -> None:
        if self._metrics_collector is not None:
            if request_id is None:
                self._metrics_collector.record_error(session_id, code=code, message=message)
            else:
                self._metrics_collector.fail_request(
                    session_id=session_id,
                    request_id=request_id,
                    code=code,
                    message=message,
                )
        await self._connection_manager.send_error(session_id, code=code, message=message)

    async def send_event(self, event: ServerEventBase) -> None:
        await self._connection_manager.send_event(event)

    async def send_session_state(self, session_id: UUID) -> None:
        session = self._session_manager.get_session(session_id)
        if session is None:
            await self.send_error(session_id, code="session_not_found", message="Session not found")
            return

        simulator_state: SimulatorState | None = None
        if self._execution_service is not None:
            try:
                simulator_state = await self._execution_service.get_state(session_id)
            except ExecutionServiceError as error:
                await self.send_error(session_id, code=error.code, message=error.message)

        await self.send_event(
            SessionStateEvent(
                session_id=session_id,
                payload=SessionStatePayload(
                    session_id=session.session_id,
                    status=session.status,
                    simulator_state=simulator_state,
                ),
            )
        )

    async def send_transcription_started(self, session_id: UUID, request_id: UUID) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.start_request(session_id, request_id)
            self._metrics_collector.start_stage(session_id, request_id, TraceStage.TRANSCRIPTION)
        await self.send_event(
            TranscriptionStartedEvent(
                session_id=session_id,
                payload=TranscriptionStartedPayload(
                    session_id=session_id,
                    request_id=request_id,
                ),
            )
        )

    async def send_transcription_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        result: TranscriptionResult,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.complete_stage(
                session_id,
                request_id,
                TraceStage.TRANSCRIPTION,
                duration_ms=result.duration_ms,
            )
        await self.send_event(
            TranscriptionCompletedEvent(
                session_id=session_id,
                payload=TranscriptionCompletedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    text=result.text,
                    language=result.language,
                    duration_ms=result.duration_ms,
                ),
            )
        )

    async def handle_transcription_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        result: TranscriptionResult,
    ) -> None:
        await self.send_transcription_completed(session_id, request_id, result)
        if self._orchestrator is None:
            return

        await self.send_llm_started(session_id, request_id)

        try:
            llm_result = await self._orchestrator.generate(session_id, request_id, result)
        except OrchestratorError as error:
            await self.send_error(
                session_id,
                code=error.code,
                message=error.message,
                request_id=request_id,
            )
            return

        await self.send_llm_completed(session_id, request_id, llm_result.duration_ms)
        await self.send_assistant_response(session_id, request_id, llm_result.assistant_text)
        await self._handle_assistant_audio(session_id, request_id, llm_result.assistant_text)
        await self.send_action_decided(session_id, request_id, llm_result.action)

    async def send_llm_started(self, session_id: UUID, request_id: UUID) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.start_stage(session_id, request_id, TraceStage.LLM)
        await self.send_event(
            LLMStartedEvent(
                session_id=session_id,
                payload=LLMStartedPayload(
                    session_id=session_id,
                    request_id=request_id,
                ),
            )
        )

    async def send_llm_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        duration_ms: int,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.complete_stage(
                session_id,
                request_id,
                TraceStage.LLM,
                duration_ms=duration_ms,
            )
        await self.send_event(
            LLMCompletedEvent(
                session_id=session_id,
                payload=LLMCompletedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    duration_ms=duration_ms,
                ),
            )
        )

    async def send_assistant_response(self, session_id: UUID, request_id: UUID, text: str) -> None:
        await self.send_event(
            AssistantResponseEvent(
                session_id=session_id,
                payload=AssistantResponsePayload(
                    session_id=session_id,
                    request_id=request_id,
                    text=text,
                ),
            )
        )

    async def send_tts_started(self, session_id: UUID, request_id: UUID, text_length: int) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.start_stage(session_id, request_id, TraceStage.TTS)
        await self.send_event(
            TTSStartedEvent(
                session_id=session_id,
                payload=TTSStartedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    text_length=text_length,
                ),
            )
        )

    async def send_tts_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        asset_id: UUID,
        duration_ms: int,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.complete_stage(
                session_id,
                request_id,
                TraceStage.TTS,
                duration_ms=duration_ms,
            )
        await self.send_event(
            TTSCompletedEvent(
                session_id=session_id,
                payload=TTSCompletedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    asset_id=asset_id,
                    duration_ms=duration_ms,
                ),
            )
        )

    async def send_assistant_audio_ready(
        self,
        session_id: UUID,
        request_id: UUID,
        asset: AudioAsset,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.mark_end_to_end(session_id, request_id)
            if self._execution_service is None:
                self._metrics_collector.complete_request(session_id, request_id)
        await self.send_event(
            AssistantAudioReadyEvent(
                session_id=session_id,
                payload=AssistantAudioReadyPayload(
                    session_id=session_id,
                    request_id=request_id,
                    asset_id=asset.asset_id,
                    url=asset.url,
                    content_type=asset.content_type,
                ),
            )
        )

    async def send_action_decided(
        self,
        session_id: UUID,
        request_id: UUID,
        action: ActionDecision,
    ) -> None:
        await self.send_event(
            ActionDecidedEvent(
                session_id=session_id,
                payload=ActionDecidedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    action=action,
                ),
            )
        )
        if self._metrics_collector is not None:
            if self._execution_service is None and self._tts_service is None:
                self._metrics_collector.complete_request(session_id, request_id)
        await self._execute_action(session_id, request_id, action)

    async def send_action_execution_started(
        self,
        session_id: UUID,
        request_id: UUID,
        action: ActionDecision,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.start_stage(session_id, request_id, TraceStage.EXECUTION)
        await self.send_event(
            ActionExecutionStartedEvent(
                session_id=session_id,
                payload=ActionExecutionStartedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    action=action,
                ),
            )
        )

    async def send_action_execution_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        action: ActionDecision,
        success: bool,
        duration_ms: int,
    ) -> None:
        if self._metrics_collector is not None:
            self._metrics_collector.complete_stage(
                session_id,
                request_id,
                TraceStage.EXECUTION,
                duration_ms=duration_ms,
            )
            if success:
                self._metrics_collector.complete_request(session_id, request_id)
        await self.send_event(
            ActionExecutionCompletedEvent(
                session_id=session_id,
                payload=ActionExecutionCompletedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    success=success,
                    action=action,
                    duration_ms=duration_ms,
                ),
            )
        )

    async def send_simulator_state_updated(
        self,
        session_id: UUID,
        state: SimulatorState,
    ) -> None:
        await self.send_event(
            SimulatorStateUpdatedEvent(
                session_id=session_id,
                payload=SimulatorStateUpdatedPayload(
                    session_id=session_id,
                    state=state,
                ),
            )
        )

    async def send_live_audio_started(self, session_id: UUID) -> None:
        await self.send_event(
            LiveAudioStartedEvent(
                session_id=session_id,
                payload=LiveAudioStartedPayload(session_id=session_id),
            )
        )

    async def send_live_audio_utterance_captured(
        self,
        session_id: UUID,
        request_id: UUID,
        duration_ms: int,
    ) -> None:
        await self.send_event(
            LiveAudioUtteranceCapturedEvent(
                session_id=session_id,
                payload=LiveAudioUtteranceCapturedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    duration_ms=duration_ms,
                ),
            )
        )

    async def send_live_audio_processing_started(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> None:
        await self.send_event(
            LiveAudioProcessingStartedEvent(
                session_id=session_id,
                payload=LiveAudioProcessingStartedPayload(
                    session_id=session_id,
                    request_id=request_id,
                ),
            )
        )

    async def send_live_audio_processing_completed(
        self,
        session_id: UUID,
        request_id: UUID,
        status: str,
    ) -> None:
        await self.send_event(
            LiveAudioProcessingCompletedEvent(
                session_id=session_id,
                payload=LiveAudioProcessingCompletedPayload(
                    session_id=session_id,
                    request_id=request_id,
                    status=status,
                ),
            )
        )

    async def send_live_audio_idle(self, session_id: UUID) -> None:
        await self.send_event(
            LiveAudioIdleEvent(
                session_id=session_id,
                payload=LiveAudioIdlePayload(session_id=session_id),
            )
        )

    async def _handle_client_ping(self, event: ClientPingEvent) -> None:
        session_id = event.session_id
        if session_id is None:
            raise SessionRuntimeNotReadyError(
                "Client events must be bound to a session before publishing"
            )
        await self.send_event(
            ServerPongEvent(
                session_id=session_id,
                payload=ServerPongPayload(message=event.payload.message),
            )
        )

    async def _handle_session_request_state(self, event: SessionRequestStateEvent) -> None:
        session_id = event.session_id
        if session_id is None:
            raise SessionRuntimeNotReadyError(
                "Client events must be bound to a session before publishing"
            )
        await self.send_session_state(session_id)

    async def _handle_assistant_audio(
        self,
        session_id: UUID,
        request_id: UUID,
        text: str,
    ) -> None:
        if self._tts_service is None:
            return
        if not text.strip():
            return

        await self.send_tts_started(session_id, request_id, len(text))

        try:
            asset = await self._tts_service.synthesize_assistant_response(
                session_id=session_id,
                request_id=request_id,
                text=text,
            )
        except TTSServiceError as error:
            await self.send_error(
                session_id,
                code=error.code,
                message=error.message,
                request_id=request_id,
            )
            return

        await self.send_tts_completed(
            session_id=session_id,
            request_id=request_id,
            asset_id=asset.asset_id,
            duration_ms=asset.duration_ms or 0,
        )
        await self.send_assistant_audio_ready(
            session_id=session_id,
            request_id=request_id,
            asset=asset,
        )

    async def _execute_action(
        self,
        session_id: UUID,
        request_id: UUID,
        action: ActionDecision,
    ) -> None:
        if self._execution_service is None:
            return

        await self.send_action_execution_started(session_id, request_id, action)

        try:
            result = await self._execution_service.execute_action(session_id, action)
        except ExecutionServiceError as error:
            await self.send_action_execution_completed(
                session_id=session_id,
                request_id=request_id,
                action=action,
                success=False,
                duration_ms=0,
            )
            await self.send_error(
                session_id,
                code=error.code,
                message=error.message,
                request_id=request_id,
            )
            return

        await self.send_action_execution_completed(
            session_id=session_id,
            request_id=request_id,
            action=result.action,
            success=result.success,
            duration_ms=result.duration_ms,
        )
        await self.send_simulator_state_updated(session_id, result.state)

    async def _ensure_runtime(self, session_id: UUID) -> RuntimeSession:
        async with self._lock:
            runtime = self._runtimes.get(session_id)
            if runtime is not None:
                return runtime

            event_bus = EventBus()
            event_bus.subscribe("client.ping", self._handle_client_ping)
            event_bus.subscribe("session.request_state", self._handle_session_request_state)

            runtime = RuntimeSession(session_id=session_id, event_bus=event_bus)
            self._runtimes[session_id] = runtime
            return runtime

    async def _get_runtime(self, session_id: UUID) -> RuntimeSession | None:
        async with self._lock:
            return self._runtimes.get(session_id)

    async def _remove_runtime(self, session_id: UUID) -> None:
        async with self._lock:
            self._runtimes.pop(session_id, None)
