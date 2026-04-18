from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from app.models.action import ActionDecision, ActionName
from app.models.simulator import ActionExecutionResult, SimulatorState
from app.services.simulator.base import (
    InvalidActionParametersError,
    Simulator,
    UnsupportedActionError,
)


class LowFidelitySimulator(Simulator):
    def __init__(self) -> None:
        self._state_by_session: dict[UUID, SimulatorState] = {}
        self._lock = asyncio.Lock()

    async def initialize_session(self, session_id: UUID) -> SimulatorState:
        async with self._lock:
            state = self._state_by_session.get(session_id)
            if state is None:
                state = self._default_state()
                self._state_by_session[session_id] = state
            return state.model_copy(deep=True)

    async def execute_action(
        self,
        session_id: UUID,
        action: ActionDecision,
    ) -> ActionExecutionResult:
        started_at = perf_counter()

        async with self._lock:
            state = self._state_by_session.get(session_id)
            if state is None:
                state = self._default_state()

            updated_state = self._apply_action(state, action)
            self._state_by_session[session_id] = updated_state

        return ActionExecutionResult(
            action=action.model_copy(deep=True),
            success=True,
            state=updated_state.model_copy(deep=True),
            duration_ms=int((perf_counter() - started_at) * 1000),
        )

    async def get_state(self, session_id: UUID) -> SimulatorState | None:
        async with self._lock:
            state = self._state_by_session.get(session_id)
            if state is None:
                return None
            return state.model_copy(deep=True)

    def _apply_action(self, state: SimulatorState, action: ActionDecision) -> SimulatorState:
        try:
            action_name = action.resolved_name()
        except ValueError as error:
            raise UnsupportedActionError(str(action.name)) from error
        updated_at = datetime.now(timezone.utc)

        if action_name == ActionName.MOVE_FORWARD:
            speed = self._read_non_negative_float(action.parameters, "speed", default=1.0)
            return state.model_copy(
                update={
                    "velocity": speed,
                    "is_moving": True,
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        if action_name == ActionName.TURN_LEFT:
            degrees = self._read_non_negative_float(action.parameters, "degrees", default=90.0)
            return state.model_copy(
                update={
                    "heading_deg": (state.heading_deg - degrees) % 360,
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        if action_name == ActionName.TURN_RIGHT:
            degrees = self._read_non_negative_float(action.parameters, "degrees", default=90.0)
            return state.model_copy(
                update={
                    "heading_deg": (state.heading_deg + degrees) % 360,
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        if action_name == ActionName.STOP:
            return state.model_copy(
                update={
                    "velocity": 0.0,
                    "is_moving": False,
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        if action_name == ActionName.STATUS_REPORT:
            return state.model_copy(
                update={
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        if action_name == ActionName.NONE:
            return state.model_copy(
                update={
                    "last_action": action_name,
                    "updated_at": updated_at,
                }
            )

        raise UnsupportedActionError(str(action.name))

    def _read_non_negative_float(
        self,
        parameters: dict[str, object],
        key: str,
        default: float,
    ) -> float:
        value = parameters.get(key, default)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as error:
            raise InvalidActionParametersError(f"Invalid value for {key}: {value}") from error
        if numeric_value < 0:
            raise InvalidActionParametersError(f"Invalid value for {key}: {value}")
        return numeric_value

    def _default_state(self) -> SimulatorState:
        return SimulatorState(
            heading_deg=0.0,
            velocity=0.0,
            is_moving=False,
            last_action=None,
            updated_at=datetime.now(timezone.utc),
        )
