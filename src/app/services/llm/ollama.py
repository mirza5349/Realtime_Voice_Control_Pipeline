from __future__ import annotations

from time import perf_counter

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.models.llm import LLMGenerationRequest, LLMGenerationResult, LLMStructuredOutput
from app.services.llm.base import (
    LLMConfigurationError,
    LLMProvider,
    LLMRequestError,
    LLMResponseError,
)


class OllamaChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    message: OllamaChatMessage
    total_duration: int | None = None


class OllamaLLMProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        if not self._base_url:
            raise LLMConfigurationError("OLLAMA_BASE_URL is required")
        if not self._model:
            raise LLMConfigurationError("OLLAMA_MODEL is required")

        started_at = perf_counter()

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {
                                "role": message.role.value,
                                "content": message.content,
                            }
                            for message in request.messages
                        ],
                        "stream": False,
                        "format": LLMStructuredOutput.model_json_schema(),
                        "options": {"temperature": 0},
                    },
                )
        except httpx.RequestError as error:
            raise LLMRequestError(str(error)) from error

        if response.status_code >= 400:
            detail = (
                response.text.strip() or f"Ollama request failed with status {response.status_code}"
            )
            raise LLMRequestError(detail)

        try:
            ollama_response = OllamaChatResponse.model_validate(response.json())
        except ValidationError as error:
            raise LLMResponseError(error.json()) from error
        except ValueError as error:
            raise LLMResponseError(str(error)) from error

        try:
            structured_output = LLMStructuredOutput.model_validate_json(
                ollama_response.message.content
            )
        except ValidationError as error:
            raise LLMResponseError(error.json()) from error
        except ValueError as error:
            raise LLMResponseError(str(error)) from error

        duration_ms = ollama_response.total_duration
        if duration_ms is None:
            duration_ms = int((perf_counter() - started_at) * 1000)
        else:
            duration_ms = max(0, duration_ms // 1_000_000)

        return LLMGenerationResult(
            assistant_text=structured_output.assistant_text,
            action=structured_output.action,
            provider="ollama",
            model=ollama_response.model,
            duration_ms=duration_ms,
        )
