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
from fitmas.runtime_v0.meso.verifier import Mode, WeekVerdict, blocked_weekday_indices, limits_intensity, verify_week
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


@dataclass(frozen=True)
class WeekProposal:
    week: PlannedWeek
    verdict: WeekVerdict
    source: Literal["llm", "template_fallback"]
    attempts: int


def generate_week(
    llm: LLMClient,
    pack: ContextPack,
    week_start: date,
    mode: Mode = "continuity",
    max_attempts: int = 3,
) -> WeekProposal:
    """Generate one typed week from the pack, looping generate->verify, then fallback.

    Requires pack.target (continuity); cold-start seed is out of scope (Slice 3).
    """
    if pack.target is None:
        raise ValueError("generate_week requires a target (continuity); cold-start is Slice 3")
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": render_generation_prompt(pack, week_start, mode)}
    ]
    for attempt in range(1, max_attempts + 1):
        response = llm.chat_with_tools(GENERATION_SYSTEM, messages, [EMIT_WEEK_TOOL])
        call = _emit_call(response)
        if call is None:
            messages.append(_contract_msg("emit the week via the emit_week tool, no prose"))
            continue
        try:
            week = _build_week(call.args.get("sessions", []))
        except (ValueError, KeyError, TypeError) as exc:
            messages.append(_contract_msg(f"invalid week: {exc}"))
            continue
        verdict = verify_week(week, pack.target, pack.constraints, mode)
        if verdict.ok:
            return WeekProposal(week=week, verdict=verdict, source="llm", attempts=attempt)
        messages.append(_violations_msg(verdict.violations))
    week = _template_week(pack.target, pack.constraints, week_start)
    verdict = verify_week(week, pack.target, pack.constraints, mode)
    return WeekProposal(week=week, verdict=verdict, source="template_fallback", attempts=max_attempts)


def _template_week(
    target: WeekTarget, constraints: tuple[TypedConstraint, ...], week_start: date
) -> PlannedWeek:
    """A deterministic standard running week sized to the band — the safety-net fallback.

    Targets the band midpoint across a fixed shape (key + long + easies), spaced so the
    two high-stress days aren't adjacent. Under an active intensity/all constraint the key
    becomes an easy run (no hard work). Under an availability constraint, sessions are
    placed only on available weekdays (blocked days carry no session), matching the verifier.
    """
    low, high = target.load_band
    mid = (low + high) / 2
    intensity_blocked = limits_intensity(constraints)
    blocked = blocked_weekday_indices(constraints)
    available = [offset for offset in range(7) if offset not in blocked] or [0]
    offsets = _spread(available, 4)

    def session(offset: int, kind: str, frac: float, intensity: str, weight: float) -> TypedSession:
        return TypedSession(
            date=week_start + timedelta(days=offset),
            type=kind,
            duration_min=max(10, round(mid * frac / weight)),
            intensity=intensity,
            detail="template fallback",
        )

    # role specs in order; trimmed to the number of available offsets (degenerate weeks)
    specs = [
        ("easy_run", 0.30, "easy", 1.0) if intensity_blocked else (target.key_type, 0.30, "hard", 2.0),
        ("easy_run", 0.20, "easy", 1.0),
        ("easy_run", 0.15, "easy", 1.0),
        ("long_run", 0.35, "moderate", 1.5),
    ]
    specs = specs[: len(offsets)]
    # put long_run last (most spaced from the key) when we have >= 2 sessions
    sessions = [session(offset, *spec) for offset, spec in zip(offsets, specs)]
    return PlannedWeek(sessions=tuple(sessions))


def _spread(days: list[int], n: int) -> list[int]:
    """Up to n evenly-spread distinct offsets from `days` (already sorted ascending)."""
    if len(days) <= n:
        return days
    step = (len(days) - 1) / (n - 1)
    return [days[round(i * step)] for i in range(n)]


def _emit_call(response: LLMResponse) -> ToolCall | None:
    for call in response.tool_calls:
        if call.name == "emit_week":
            return call
    return None


def _contract_msg(error: str) -> dict[str, Any]:
    return {"role": "tool", "tool_name": "contract", "content": json.dumps({"error": error}, ensure_ascii=False)}


def _violations_msg(violations: tuple[Any, ...]) -> dict[str, Any]:
    payload = [{"code": v.code, "detail": v.detail, "severity": v.severity} for v in violations]
    return {"role": "tool", "tool_name": "verifier", "content": json.dumps(payload, ensure_ascii=False)}
