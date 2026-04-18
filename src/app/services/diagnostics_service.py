from __future__ import annotations

from uuid import UUID

from app.models.metrics import MetricsSummary, SessionDiagnostics
from app.models.session import SessionStatus
from app.services.connection_manager import ConnectionManager
from app.services.execution_service import ExecutionService, ExecutionServiceError
from app.services.metrics_collector import MetricsCollector
from app.services.session_manager import SessionManager


class DiagnosticsServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DiagnosticsService:
    def __init__(
        self,
        session_manager: SessionManager,
        connection_manager: ConnectionManager,
        metrics_collector: MetricsCollector,
        execution_service: ExecutionService | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._connection_manager = connection_manager
        self._metrics_collector = metrics_collector
        self._execution_service = execution_service

    def set_execution_service(self, execution_service: ExecutionService | None) -> None:
        self._execution_service = execution_service

    async def get_metrics_summary(self) -> MetricsSummary:
        sessions = self._session_manager.list_sessions()
        active_sessions = sum(session.status == SessionStatus.ACTIVE for session in sessions)
        active_websockets = await self._connection_manager.connection_count()
        return self._metrics_collector.build_summary(
            active_sessions=active_sessions,
            active_websockets=active_websockets,
        )

    async def get_session_diagnostics(self, session_id: UUID) -> SessionDiagnostics:
        session = self._session_manager.get_session(session_id)
        if session is None:
            raise DiagnosticsServiceError("session_not_found", "Session not found")

        active_connection = await self._connection_manager.has_connection(session_id)
        current_simulator_state = None
        if self._execution_service is not None:
            try:
                current_simulator_state = await self._execution_service.get_state(session_id)
            except ExecutionServiceError as error:
                raise DiagnosticsServiceError(error.code, error.message) from error

        return SessionDiagnostics(
            session_id=session.session_id,
            session_status=session.status,
            active_connection=active_connection,
            current_simulator_state=current_simulator_state,
            recent_requests=self._metrics_collector.get_session_traces(session_id),
            last_error=self._metrics_collector.get_last_error(session_id),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
