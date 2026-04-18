from __future__ import annotations

from uuid import UUID

from app.models.action import ActionDecision
from app.models.simulator import ActionExecutionResult, SimulatorState
from app.services.simulator.base import Simulator, SimulatorError


class ExecutionServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ExecutionService:
    def __init__(self, simulator: Simulator) -> None:
        self._simulator = simulator

    async def initialize_session(self, session_id: UUID) -> SimulatorState:
        try:
            return await self._simulator.initialize_session(session_id)
        except SimulatorError as error:
            raise ExecutionServiceError(error.code, error.message) from error

    async def execute_action(
        self,
        session_id: UUID,
        action: ActionDecision,
    ) -> ActionExecutionResult:
        try:
            return await self._simulator.execute_action(session_id, action)
        except SimulatorError as error:
            raise ExecutionServiceError(error.code, error.message) from error

    async def get_state(self, session_id: UUID) -> SimulatorState | None:
        try:
            return await self._simulator.get_state(session_id)
        except SimulatorError as error:
            raise ExecutionServiceError(error.code, error.message) from error
