from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class LocalTimeContext:
    timezone_name: str
    now_iso: str
    today_iso: str
    time_context: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PlanTimeline:
    scheduled_sessions: tuple[Any, ...]
    session_policies: tuple[Any, ...]
    planning_contract: Any | None
    week_mission: Any | None
    latest_adaptation: Any | None
    recent_adaptations: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ExecutionReality:
    activities: tuple[Any, ...]
    recent_reality: Any | None
    today_execution: Any | None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    active_memory: tuple[Any, ...]
    active_facts: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AthleteContext:
    profile_snapshot: Any | None
    calibration_status: Any | None


@dataclass(frozen=True, slots=True)
class ReadinessContext:
    snapshot: Any | None
    state: Any | None


@dataclass(frozen=True, slots=True)
class LoadContext:
    summary: Mapping[str, Any] | None
    forecast: Any | None


@dataclass(frozen=True, slots=True)
class WeeklyRealityDigest:
    week_summary: Mapping[str, Any]
    planning_context: Mapping[str, Any]
    next_week: Mapping[str, Any]
    coach_reading: str


@dataclass(frozen=True, slots=True)
class PendingContext:
    active_pending: Any | None
    summary: str | None


@dataclass(frozen=True, slots=True)
class CoachContext:
    user: Any
    local_time: LocalTimeContext
    plan: PlanTimeline
    execution: ExecutionReality
    memory: MemoryContext
    athlete: AthleteContext
    readiness: ReadinessContext
    load: LoadContext
    weekly_digest: WeeklyRealityDigest
    pending: PendingContext
