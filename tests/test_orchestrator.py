import asyncio
from uuid import uuid4

import pytest

from app.models.action import ActionDecision, ActionName
from app.models.llm import LLMGenerationResult
from app.models.transcription import TranscriptionResult
from app.services.llm.base import LLMProvider, LLMResponseError
from app.services.orchestrator import Orchestrator, OrchestratorError
from app.services.prompt_builder import PromptBuilder


class RecordingLLMProvider(LLMProvider):
    def __init__(self, responses: list[LLMGenerationResult]) -> None:
        self._responses = responses
        self.requests = []

    async def generate(self, request):  # type: ignore[override]
        self.requests.append(request)
        return self._responses.pop(0)


class FailingLLMProvider(LLMProvider):
    async def generate(self, request):  # type: ignore[override]
        raise LLMResponseError("Model returned invalid structured output")


def test_orchestrator_builds_history_with_bounded_limit() -> None:
    session_id = uuid4()
    provider = RecordingLLMProvider(
        responses=[
            LLMGenerationResult(
                assistant_text="Moving forward.",
                action=ActionDecision(name=ActionName.MOVE_FORWARD, parameters={"distance_m": 1}),
                provider="fake_llm",
                model="fake-model",
                duration_ms=12,
            ),
            LLMGenerationResult(
                assistant_text="Holding position.",
                action=ActionDecision(name=ActionName.STOP, parameters={}),
                provider="fake_llm",
                model="fake-model",
                duration_ms=10,
            ),
        ]
    )
    orchestrator = Orchestrator(provider, PromptBuilder(), history_limit=2)

    first_result = asyncio.run(
        orchestrator.generate(
            session_id,
            uuid4(),
            TranscriptionResult(
                text="move forward",
                language="en",
                duration_ms=50,
                provider="fake_stt",
            ),
        )
    )
    second_result = asyncio.run(
        orchestrator.generate(
            session_id,
            uuid4(),
            TranscriptionResult(
                text="stop",
                language="en",
                duration_ms=40,
                provider="fake_stt",
            ),
        )
    )
    history = asyncio.run(orchestrator.get_history(session_id))

    assert first_result.assistant_text == "Moving forward."
    assert second_result.assistant_text == "Holding position."
    assert provider.requests[0].messages[-1].content == "move forward"
    assert provider.requests[1].messages[-1].content == "stop"
    assert [message.content for message in history] == ["stop", "Holding position."]


def test_orchestrator_raises_typed_error_for_provider_failures() -> None:
    session_id = uuid4()
    orchestrator = Orchestrator(FailingLLMProvider(), PromptBuilder(), history_limit=4)

    with pytest.raises(OrchestratorError) as error:
        asyncio.run(
            orchestrator.generate(
                session_id,
                uuid4(),
                TranscriptionResult(
                    text="status",
                    language="en",
                    duration_ms=30,
                    provider="fake_stt",
                ),
            )
        )

    history = asyncio.run(orchestrator.get_history(session_id))

    assert error.value.code == "llm_response_invalid"
    assert error.value.message == "Model returned invalid structured output"
    assert [message.content for message in history] == ["status"]
