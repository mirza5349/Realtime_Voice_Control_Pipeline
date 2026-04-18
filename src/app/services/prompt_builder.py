from __future__ import annotations

import json
from uuid import UUID

from app.models.action import ActionName
from app.models.llm import (
    ConversationMessage,
    ConversationRole,
    LLMGenerationRequest,
    LLMStructuredOutput,
)


class PromptBuilder:
    def build(
        self,
        session_id: UUID,
        request_id: UUID,
        history: list[ConversationMessage],
        latest_user_text: str,
    ) -> LLMGenerationRequest:
        schema = json.dumps(LLMStructuredOutput.model_json_schema(), separators=(",", ":"))
        allowed_actions = ", ".join(action.value for action in ActionName)

        system_message = ConversationMessage(
            role=ConversationRole.SYSTEM,
            content=(
                "You are the assistant for a local voice AI pipeline. "
                f"Return only JSON that matches this schema: {schema}. "
                "The assistant_text field should be concise and conversational. "
                f"The action.name field must be one of: {allowed_actions}. "
                "Use action.parameters as an object and keep it empty when no action is needed."
            ),
        )
        user_message = ConversationMessage(role=ConversationRole.USER, content=latest_user_text)

        return LLMGenerationRequest(
            session_id=session_id,
            request_id=request_id,
            messages=[system_message, *history, user_message],
        )
