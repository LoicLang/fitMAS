from __future__ import annotations

from typing import Any

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolSchema

class FakeLLMClient:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def chat_with_tools(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> LLMResponse:
        self.requests.append(
            {
                "system": system,
                "messages": [dict(message) for message in messages],
                "tools": list(tools),
            }
        )
        if not self._responses:
            raise RuntimeError("no_scripted_response")
        return self._responses.pop(0)
