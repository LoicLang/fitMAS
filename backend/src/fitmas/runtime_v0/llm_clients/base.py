from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    is_proposal: bool


class LLMClient(Protocol):
    def chat_with_tools(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> LLMResponse:
        ...
