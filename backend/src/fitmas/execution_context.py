from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from fitmas.time_context import get_local_now, get_timezone

REST_SPORTS = {"rest", "off"}


@dataclass(frozen=True, slots=True)
class ActivityExecutionSummary:
    activity_id: int | None
    sport_type: str
    title: str
    local_date: date
    duration_min: int | None
    scheduled_session_id: int | None


@dataclass(frozen=True, slots=True)
class TodayExecutionContext:
    local_date: date
    planned_session_id: int | None
    planned_sport: str | None
    planned_title: str | None
    planned_duration_min: int | None
    planned_completion_status: str | None
    activity_count_today: int
    actual_sports_today: tuple[str, ...]
    actual_duration_min_today: int
    linked_activity_id: int | None
    execution_status: str
    status_reason: str
    recent_activities: tuple[ActivityExecutionSummary, ...]


def build_today_execution_context(
    *,
    timezone_name: str | None,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
    now: datetime | None = None,
    recent_days: int = 3,
) -> TodayExecutionContext:
    local_today = get_local_now(timezone_name, now=now).date()
    recent_window_start = local_today.fromordinal(local_today.toordinal() - max(0, recent_days - 1))
    planned_session = _pick_today_session(scheduled_sessions, local_today=local_today, timezone_name=timezone_name)
    recent_activities = tuple(
        activity
        for activity in _summarize_activities(activities, timezone_name=timezone_name)
        if recent_window_start <= activity.local_date <= local_today
    )
    activities_today = [activity for activity in recent_activities if activity.local_date == local_today]
    actual_sports_today = tuple(_dedupe(activity.sport_type for activity in activities_today))
    actual_duration_min_today = sum(activity.duration_min or 0 for activity in activities_today)
    linked_activity = next(
        (
            activity
            for activity in activities_today
            if planned_session is not None and activity.scheduled_session_id == _value(planned_session, "id")
        ),
        None,
    )
    execution_status, status_reason = _classify_execution(
        planned_session=planned_session,
        activities_today=activities_today,
        linked_activity=linked_activity,
    )
    return TodayExecutionContext(
        local_date=local_today,
        planned_session_id=_value(planned_session, "id"),
        planned_sport=_value(planned_session, "sport_type"),
        planned_title=_value(planned_session, "session_title"),
        planned_duration_min=_value(planned_session, "duration_min"),
        planned_completion_status=_value(planned_session, "completion_status"),
        activity_count_today=len(activities_today),
        actual_sports_today=actual_sports_today,
        actual_duration_min_today=actual_duration_min_today,
        linked_activity_id=linked_activity.activity_id if linked_activity else None,
        execution_status=execution_status,
        status_reason=status_reason,
        recent_activities=tuple(
            sorted(recent_activities, key=lambda activity: (activity.local_date, activity.activity_id or 0), reverse=True)
        ),
    )


def format_execution_context_for_prompt(context: TodayExecutionContext) -> str:
    recent_lines = [
        (
            f"- {activity.local_date.isoformat()} | {activity.sport_type} | "
            f"{activity.duration_min if activity.duration_min is not None else 'unknown'} min | "
            f"{activity.title or 'sans titre'}"
        )
        for activity in context.recent_activities[:5]
    ]
    recent_block = "\n".join(recent_lines) if recent_lines else "- aucune activite recente"
    return (
        "Execution reelle:\n"
        f"- date locale: {context.local_date.isoformat()}\n"
        f"- seance prevue id: {context.planned_session_id}\n"
        f"- sport prevu: {context.planned_sport or 'none'}\n"
        f"- titre prevu: {context.planned_title or 'none'}\n"
        f"- duree prevue: {context.planned_duration_min if context.planned_duration_min is not None else 'unknown'}\n"
        f"- statut seance prevue: {context.planned_completion_status or 'unknown'}\n"
        f"- nb activites aujourd'hui: {context.activity_count_today}\n"
        f"- sports reels aujourd'hui: {', '.join(context.actual_sports_today) or 'none'}\n"
        f"- duree reelle aujourd'hui: {context.actual_duration_min_today} min\n"
        f"- linked_activity_id: {context.linked_activity_id}\n"
        f"- execution_status: {context.execution_status}\n"
        f"- raison: {context.status_reason}\n"
        "Activites recentes:\n"
        f"{recent_block}\n"
    )


def _classify_execution(
    *,
    planned_session: Any | None,
    activities_today: Sequence[ActivityExecutionSummary],
    linked_activity: ActivityExecutionSummary | None,
) -> tuple[str, str]:
    if planned_session is None:
        if activities_today:
            return "off_plan_done", "Activite reelle aujourd'hui sans seance planifiee explicite."
        return "no_plan_no_activity", "Aucune seance planifiee aujourd'hui et aucune activite reelle."

    planned_sport = str(_value(planned_session, "sport_type") or "").lower()
    planned_duration = _int(_value(planned_session, "duration_min"))
    planned_status = str(_value(planned_session, "completion_status") or "").lower()
    same_sport_activity = next(
        (activity for activity in activities_today if activity.sport_type == planned_sport),
        None,
    )

    if linked_activity is not None:
        if _duration_close(linked_activity.duration_min, planned_duration):
            return "planned_done_as_expected", "Activite du jour liee explicitement a la seance prevue."
        return "planned_done_modified", "Activite du jour liee a la seance prevue mais execution differente."

    if same_sport_activity is not None:
        if _duration_close(same_sport_activity.duration_min, planned_duration):
            return "planned_done_as_expected", "Meme sport realise aujourd'hui avec charge proche du plan."
        return "planned_done_modified", "Meme sport realise aujourd'hui mais execution differente du plan."

    if activities_today:
        if planned_sport in REST_SPORTS:
            return "off_plan_done", "Jour de repos planifie mais activite reelle detectee."
        return "off_plan_done", "Activite reelle aujourd'hui mais sur un sport different du plan."

    if planned_status in {"done", "adapted"}:
        return "planned_marked_done_without_activity", "Seance marquee done/adapted sans activite persistée du jour."

    return "planned_pending", "Seance planifiee aujourd'hui sans activite reelle persistée."


def _pick_today_session(
    scheduled_sessions: Sequence[Any],
    *,
    local_today: date,
    timezone_name: str | None,
) -> Any | None:
    matching = [
        session
        for session in scheduled_sessions
        if _as_local_date(_value(session, "scheduled_date"), timezone_name) == local_today
    ]
    if not matching:
        return None
    matching.sort(
        key=lambda session: (
            str(_value(session, "sport_type") or "").lower() in REST_SPORTS,
            _value(session, "id") or 0,
        )
    )
    return matching[0]


def _summarize_activities(
    activities: Iterable[Any],
    *,
    timezone_name: str | None,
) -> list[ActivityExecutionSummary]:
    summarized: list[ActivityExecutionSummary] = []
    for activity in activities:
        local_date = _as_local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name)
        if local_date is None:
            continue
        summarized.append(
            ActivityExecutionSummary(
                activity_id=_int(_value(activity, "id")),
                sport_type=str(_value(activity, "sport_type") or "").lower() or "unknown",
                title=str(_value(activity, "title") or "").strip(),
                local_date=local_date,
                duration_min=_int(_value(activity, "duration_min")),
                scheduled_session_id=_int(_value(activity, "scheduled_session_id")),
            )
        )
    return summarized


def _duration_close(actual: int | None, planned: int | None) -> bool:
    if actual is None or planned is None:
        return False
    return abs(actual - planned) <= 15


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _as_local_date(value: Any, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    timezone = get_timezone(timezone_name)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(timezone).date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(timezone).date()
    return None


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
