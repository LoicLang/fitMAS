"""Meso week generator (Slice 2.1).

LLM-first: the LLM emits a typed week via the emit_week tool; a generate->verify loop
judges it; a deterministic template is the fallback. Calls an injected LLMClient (real
providers live in scripts/v0_eval/). Everything pending. See the Slice 2.1 design.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from typing import Any, Literal

from fitmas.runtime_v0.llm_clients.base import LLMClient, LLMResponse, ToolCall, ToolSchema
from fitmas.runtime_v0.meso.model import (
    ContextPack,
    PlannedWeek,
    TypedConstraint,
    TypedSession,
    WeekTarget,
)
from fitmas.runtime_v0.meso.verifier import Mode, WeekVerdict, limits_intensity, verify_week
from fitmas.runtime_v0.prompts.week_generation import GENERATION_SYSTEM, render_generation_prompt

_SESSION_TYPES = {"rest", "easy_run", "long_run", "threshold", "intervals", "recovery_run"}
_INTENSITIES = {"easy", "moderate", "hard"}


def _build_week(sessions: list[dict[str, Any]]) -> PlannedWeek:
    """Parse the LLM's emit_week args into a typed week. Raise ValueError on bad enums."""
    built: list[TypedSession] = []
    for raw in sessions:
        kind = raw.get("type")
        intensity = raw.get("intensity")
        if kind not in _SESSION_TYPES:
            raise ValueError(f"bad session type {kind!r}")
        if intensity not in _INTENSITIES:
            raise ValueError(f"bad intensity {intensity!r}")
        built.append(
            TypedSession(
                date=date.fromisoformat(raw["date"]),
                type=kind,
                duration_min=int(raw["duration_min"]),
                intensity=intensity,
                detail=raw.get("detail", ""),
            )
        )
    return PlannedWeek(sessions=tuple(built))


EMIT_WEEK_TOOL = ToolSchema(
    name="emit_week",
    description="Emit the planned running week as a list of typed sessions.",
    parameters={
        "type": "object",
        "properties": {
            "sessions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "type": {"type": "string", "enum": sorted(_SESSION_TYPES)},
                        "duration_min": {"type": "integer", "minimum": 0},
                        "intensity": {"type": "string", "enum": sorted(_INTENSITIES)},
                        "detail": {"type": "string"},
                    },
                    "required": ["date", "type", "duration_min", "intensity"],
                },
            }
        },
        "required": ["sessions"],
    },
    handler=_build_week,
    is_proposal=True,
)
