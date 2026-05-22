from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.core.time_context import DAY_KEYS, get_local_now, get_timezone


@dataclass(frozen=True, slots=True)
class PlanningWindowCandidate:
    session_id: int
    scheduled_date: date
    day_key: str
    part_of_day: str | None
    sport_type: str
    session_title: str
    completion_status: str
    priority: str


@dataclass(frozen=True, slots=True)
class PlanningWindowResolution:
    reference_label: str
    scope: str
    resolved_date: date | None
    window: str | None
    candidate_sessions: tuple[PlanningWindowCandidate, ...]
    matched_session_id: int | None
    exact_match: bool
    needs_clarification: bool
    clarification_reason: str | None = None


def resolve_planning_window_inputs(
    *,
    reference_label: str,
    resolved_date: date | None,
    day_key: str | None,
    window: str | None,
    scope: str,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
    now: datetime | None = None,
    horizon_days: int = 7,
    limit: int = 8,
) -> PlanningWindowResolution:
    local_today = get_local_now(timezone_name, now=now).date()
    start_date = resolved_date or local_today
    end_date = start_date if scope in {"single_window", "single_day"} else start_date + timedelta(days=max(1, horizon_days - 1))

    candidates: list[PlanningWindowCandidate] = []
    for session in scheduled_sessions:
        scheduled_at = _session_datetime(session, timezone_name=timezone_name)
        if scheduled_at is None:
            continue
        session_date = scheduled_at.date()
        if session_date < start_date or session_date > end_date:
            continue
        completion_status = str(_value(session, "completion_status") or "")
        if completion_status not in {"planned", "adapted"}:
            continue
        sport_type = str(_value(session, "sport_type") or "")
        if sport_type == "rest":
            continue
        candidate = PlanningWindowCandidate(
            session_id=int(_value(session, "id") or 0),
            scheduled_date=session_date,
            day_key=str(_value(session, "day") or DAY_KEYS[session_date.weekday()]),
            part_of_day=_part_of_day(scheduled_at.hour),
            sport_type=sport_type,
            session_title=str(_value(session, "session_title") or ""),
            completion_status=completion_status,
            priority=str(_value(session, "priority") or ""),
        )
        if window and candidate.part_of_day != window:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break

    matched_session_id = candidates[0].session_id if len(candidates) == 1 else None
    needs_clarification = False
    clarification_reason = None
    if not candidates:
        needs_clarification = True
        clarification_reason = "no_candidate_session"
    elif len(candidates) > 1:
        needs_clarification = True
        clarification_reason = "multiple_candidate_sessions"

    return PlanningWindowResolution(
        reference_label=reference_label,
        scope=scope,
        resolved_date=resolved_date,
        window=window,
        candidate_sessions=tuple(candidates),
        matched_session_id=matched_session_id,
        exact_match=matched_session_id is not None,
        needs_clarification=needs_clarification,
        clarification_reason=clarification_reason,
    )


def format_planning_window_summary(resolution: PlanningWindowResolution) -> str:
    if not resolution.candidate_sessions:
        return f"Aucune seance planifiee sur {resolution.reference_label}."
    if resolution.matched_session_id is not None:
        session = resolution.candidate_sessions[0]
        return (
            f"1 seance cible sur {resolution.reference_label}: "
            f"{session.session_title or session.sport_type} ({session.scheduled_date.isoformat()})."
        )
    return (
        f"{len(resolution.candidate_sessions)} seances candidates sur {resolution.reference_label}; "
        "clarification utile avant mutation."
    )


def _session_datetime(session: Any, *, timezone_name: str | None) -> datetime | None:
    value = _value(session, "scheduled_date")
    timezone = get_timezone(timezone_name)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    return None


def _part_of_day(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "midday"
    return "evening"


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
