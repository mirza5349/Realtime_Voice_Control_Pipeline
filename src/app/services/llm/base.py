from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.llm import LLMGenerationRequest, LLMGenerationResult


class LLMProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLMConfigurationError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_configuration_error", message)


class LLMRequestError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_request_failed", message)


class LLMResponseError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_response_invalid", message)


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        raise NotImplementedError
