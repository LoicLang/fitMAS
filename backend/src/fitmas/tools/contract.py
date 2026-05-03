from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    pipeline: str
    user_id: int | None
    timezone_name: str | None
    db: Any | None = None
    now: datetime | None = None
    scheduled_sessions: Sequence[Any] = ()
    activities: Sequence[Any] = ()
    active_facts: Sequence[dict[str, Any]] = ()


ToolHandler = Callable[[ToolContext, dict[str, Any]], ToolResult]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    allowed_pipelines: tuple[str, ...] = ("conversation",)
    handler: ToolHandler | None = None


def serialize_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": dict(spec.input_schema),
        "allowed_pipelines": list(spec.allowed_pipelines),
    }
