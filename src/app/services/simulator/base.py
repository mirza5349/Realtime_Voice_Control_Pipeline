from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.models.action import ActionDecision
from app.models.simulator import ActionExecutionResult, SimulatorState


class SimulatorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnsupportedActionError(SimulatorError):
    def __init__(self, action_name: str) -> None:
        super().__init__("unsupported_action", f"Unsupported action: {action_name}")


class InvalidActionParametersError(SimulatorError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_action_parameters", message)


class Simulator(ABC):
    @abstractmethod
    async def initialize_session(self, session_id: UUID) -> SimulatorState:
        raise NotImplementedError

    @abstractmethod
    async def execute_action(
        self,
        session_id: UUID,
        action: ActionDecision,
    ) -> ActionExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self, session_id: UUID) -> SimulatorState | None:
        raise NotImplementedError
