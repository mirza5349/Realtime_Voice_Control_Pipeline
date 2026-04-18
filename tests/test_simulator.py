import asyncio
from uuid import uuid4

import pytest

from app.models.action import ActionDecision, ActionName
from app.services.simulator.base import InvalidActionParametersError
from app.services.simulator.low_fidelity import LowFidelitySimulator


def test_simulator_updates_state_deterministically_per_session() -> None:
    simulator = LowFidelitySimulator()
    first_session_id = uuid4()
    second_session_id = uuid4()

    first_state = asyncio.run(simulator.initialize_session(first_session_id))
    second_state = asyncio.run(simulator.initialize_session(second_session_id))
    first_result = asyncio.run(
        simulator.execute_action(
            first_session_id,
            ActionDecision(name=ActionName.MOVE_FORWARD, parameters={"speed": 2.5}),
        )
    )
    second_result = asyncio.run(
        simulator.execute_action(
            second_session_id,
            ActionDecision(name=ActionName.TURN_LEFT, parameters={"degrees": 45}),
        )
    )

    assert first_state.heading_deg == 0.0
    assert second_state.heading_deg == 0.0
    assert first_result.state.velocity == 2.5
    assert first_result.state.is_moving is True
    assert first_result.state.last_action == ActionName.MOVE_FORWARD
    assert second_result.state.heading_deg == 315.0
    assert second_result.state.velocity == 0.0
    assert second_result.state.is_moving is False
    assert second_result.state.last_action == ActionName.TURN_LEFT


def test_simulator_rejects_invalid_action_parameters() -> None:
    simulator = LowFidelitySimulator()
    session_id = uuid4()

    asyncio.run(simulator.initialize_session(session_id))

    with pytest.raises(InvalidActionParametersError) as error:
        asyncio.run(
            simulator.execute_action(
                session_id,
                ActionDecision(name=ActionName.TURN_RIGHT, parameters={"degrees": "bad"}),
            )
        )

    assert error.value.code == "invalid_action_parameters"
    assert error.value.message == "Invalid value for degrees: bad"
