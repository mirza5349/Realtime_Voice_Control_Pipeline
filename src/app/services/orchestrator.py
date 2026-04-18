from __future__ import annotations

import asyncio
from uuid import UUID

from app.models.llm import ConversationMessage, ConversationRole, LLMGenerationResult
from app.models.transcription import TranscriptionResult
from app.services.llm.base import LLMProvider, LLMProviderError
from app.services.prompt_builder import PromptBuilder


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Orchestrator:
    def __init__(
        self,
        llm_provider: LLMProvider,
        prompt_builder: PromptBuilder,
        history_limit: int,
    ) -> None:
        self._llm_provider = llm_provider
        self._prompt_builder = prompt_builder
        self._history_limit = history_limit
        self._history: dict[UUID, list[ConversationMessage]] = {}
        self._lock = asyncio.Lock()

    async def generate(
        self,
        session_id: UUID,
        request_id: UUID,
        transcription: TranscriptionResult,
    ) -> LLMGenerationResult:
        history = await self.get_history(session_id)
        request = self._prompt_builder.build(
            session_id=session_id,
            request_id=request_id,
            history=history,
            latest_user_text=transcription.text,
        )

        await self._append_message(
            session_id,
            ConversationMessage(role=ConversationRole.USER, content=transcription.text),
        )

        try:
            result = await self._llm_provider.generate(request)
        except LLMProviderError as error:
            raise OrchestratorError(error.code, error.message) from error

        await self._append_message(
            session_id,
            ConversationMessage(role=ConversationRole.ASSISTANT, content=result.assistant_text),
        )
        return result

    async def get_history(self, session_id: UUID) -> list[ConversationMessage]:
        async with self._lock:
            history = self._history.get(session_id, [])
            return [message.model_copy(deep=True) for message in history]

    async def clear_history(self, session_id: UUID) -> None:
        async with self._lock:
            self._history.pop(session_id, None)

    async def _append_message(self, session_id: UUID, message: ConversationMessage) -> None:
        async with self._lock:
            history = self._history.setdefault(session_id, [])
            history.append(message)
            if len(history) > self._history_limit:
                del history[: -self._history_limit]
