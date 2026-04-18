from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from threading import Lock
from uuid import UUID

from app.models.metrics import MetricsSummary, RequestTrace, RequestTraceStatus, RuntimeErrorInfo
from app.services.tracing import RequestTraceState, TraceStage, utc_now


class MetricsCollector:
    def __init__(self, trace_history_limit: int, retention_limit: int) -> None:
        self._trace_history_limit = trace_history_limit
        self._retention_limit = retention_limit
        self._traces: dict[UUID, RequestTraceState] = {}
        self._session_requests: dict[UUID, deque[UUID]] = defaultdict(deque)
        self._finalized_order: deque[UUID] = deque(maxlen=retention_limit)
        self._finalized_traces: dict[UUID, RequestTrace] = {}
        self._recent_errors: deque[RuntimeErrorInfo] = deque(maxlen=retention_limit)
        self._last_error_by_session: dict[UUID, RuntimeErrorInfo] = {}
        self._completed_requests = 0
        self._failed_requests = 0
        self._lock = Lock()

    def start_request(self, session_id: UUID, request_id: UUID) -> RequestTrace:
        with self._lock:
            state = self._get_or_create_trace_locked(session_id, request_id)
            return state.to_model()

    def start_stage(self, session_id: UUID, request_id: UUID, stage: TraceStage) -> RequestTrace:
        with self._lock:
            state = self._get_or_create_trace_locked(session_id, request_id)
            state.start_stage(stage)
            self._refresh_finalized_trace_locked(request_id)
            return state.to_model()

    def complete_stage(
        self,
        session_id: UUID,
        request_id: UUID,
        stage: TraceStage,
        duration_ms: int | None = None,
    ) -> RequestTrace:
        with self._lock:
            state = self._get_or_create_trace_locked(session_id, request_id)
            state.complete_stage(stage, duration_ms=duration_ms)
            self._refresh_finalized_trace_locked(request_id)
            return state.to_model()

    def mark_end_to_end(self, session_id: UUID, request_id: UUID) -> RequestTrace:
        with self._lock:
            state = self._get_or_create_trace_locked(session_id, request_id)
            state.mark_end_to_end()
            self._refresh_finalized_trace_locked(request_id)
            return state.to_model()

    def complete_request(self, session_id: UUID, request_id: UUID) -> RequestTrace:
        with self._lock:
            state = self._get_or_create_trace_locked(session_id, request_id)
            if state.status == RequestTraceStatus.IN_PROGRESS:
                state.complete()
                self._completed_requests += 1
                self._upsert_finalized_trace_locked(request_id, state.to_model())
            return state.to_model()

    def fail_request(
        self,
        session_id: UUID,
        request_id: UUID,
        code: str,
        message: str,
    ) -> RequestTrace:
        error = RuntimeErrorInfo(
            code=code,
            message=message,
            timestamp=utc_now(),
            request_id=request_id,
        )
        with self._lock:
            self._record_error_locked(session_id, error)
            state = self._get_or_create_trace_locked(session_id, request_id)
            if state.status == RequestTraceStatus.IN_PROGRESS:
                state.fail(error)
                self._failed_requests += 1
                self._upsert_finalized_trace_locked(request_id, state.to_model())
            else:
                state.record_error(error)
                self._refresh_finalized_trace_locked(request_id)
            return state.to_model()

    def record_error(
        self,
        session_id: UUID,
        code: str,
        message: str,
        request_id: UUID | None = None,
    ) -> RuntimeErrorInfo:
        error = RuntimeErrorInfo(
            code=code,
            message=message,
            timestamp=utc_now(),
            request_id=request_id,
        )
        with self._lock:
            self._record_error_locked(session_id, error)
            if request_id is not None:
                state = self._get_or_create_trace_locked(session_id, request_id)
                state.record_error(error)
                self._refresh_finalized_trace_locked(request_id)
            return error

    def get_session_traces(self, session_id: UUID) -> list[RequestTrace]:
        with self._lock:
            request_ids = list(self._session_requests.get(session_id, ()))
            return [
                self._traces[request_id].to_model()
                for request_id in reversed(request_ids)
                if request_id in self._traces
            ]

    def get_last_error(self, session_id: UUID) -> RuntimeErrorInfo | None:
        with self._lock:
            return self._last_error_by_session.get(session_id)

    def build_summary(self, active_sessions: int, active_websockets: int) -> MetricsSummary:
        with self._lock:
            finalized = [
                self._finalized_traces[request_id]
                for request_id in self._finalized_order
                if request_id in self._finalized_traces
            ]
            return MetricsSummary(
                active_sessions=active_sessions,
                active_websockets=active_websockets,
                completed_requests=self._completed_requests,
                failed_requests=self._failed_requests,
                recent_error_count=len(self._recent_errors),
                avg_transcription_duration_ms=self._average(
                    trace.transcription_duration_ms for trace in finalized
                ),
                avg_llm_duration_ms=self._average(trace.llm_duration_ms for trace in finalized),
                avg_execution_duration_ms=self._average(
                    trace.execution_duration_ms for trace in finalized
                ),
                avg_tts_duration_ms=self._average(trace.tts_duration_ms for trace in finalized),
                avg_end_to_end_duration_ms=self._average(
                    trace.end_to_end_duration_ms for trace in finalized
                ),
            )

    def _get_or_create_trace_locked(self, session_id: UUID, request_id: UUID) -> RequestTraceState:
        state = self._traces.get(request_id)
        if state is not None:
            return state

        state = RequestTraceState(
            session_id=session_id,
            request_id=request_id,
            started_at=utc_now(),
        )
        self._traces[request_id] = state
        session_requests = self._session_requests[session_id]
        session_requests.append(request_id)
        while len(session_requests) > self._trace_history_limit:
            expired_request_id = session_requests.popleft()
            self._traces.pop(expired_request_id, None)
        return state

    def _record_error_locked(self, session_id: UUID, error: RuntimeErrorInfo) -> None:
        self._recent_errors.append(error)
        self._last_error_by_session[session_id] = error

    def _upsert_finalized_trace_locked(self, request_id: UUID, trace: RequestTrace) -> None:
        if request_id not in self._finalized_traces:
            if len(self._finalized_order) == self._retention_limit:
                expired_request_id = self._finalized_order.popleft()
                self._finalized_traces.pop(expired_request_id, None)
            self._finalized_order.append(request_id)
        self._finalized_traces[request_id] = trace

    def _refresh_finalized_trace_locked(self, request_id: UUID) -> None:
        if request_id not in self._finalized_traces:
            return
        state = self._traces.get(request_id)
        if state is not None:
            self._finalized_traces[request_id] = state.to_model()

    def _average(self, values: Iterable[int | None]) -> float | None:
        numbers = [float(value) for value in values if value is not None]
        if not numbers:
            return None
        return sum(numbers) / len(numbers)
