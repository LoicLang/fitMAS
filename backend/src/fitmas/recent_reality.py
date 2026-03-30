from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.execution_evidence import classify_execution_evidence
from fitmas.fitness_snapshot import estimate_scheduled_session_tss

KEY_PRIORITIES = {"high", "key", "important"}
REST_SPORTS = {"rest", "off"}


@dataclass(frozen=True, slots=True)
class RecentRealityWindow:
    planned_sessions_7d: int
    confirmed_sessions_7d: int
    claimed_sessions_7d: int
    key_sessions_salvaged_7d: int
    planned_tss_7d: float
    observed_tss_7d: float
    compliance_confirmed: float
    load_ratio: float
    missed_streak_days: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "planned_sessions_7d": self.planned_sessions_7d,
            "confirmed_sessions_7d": self.confirmed_sessions_7d,
            "claimed_sessions_7d": self.claimed_sessions_7d,
            "key_sessions_salvaged_7d": self.key_sessions_salvaged_7d,
            "planned_tss_7d": self.planned_tss_7d,
            "observed_tss_7d": self.observed_tss_7d,
            "compliance_confirmed": self.compliance_confirmed,
            "load_ratio": self.load_ratio,
            "missed_streak_days": self.missed_streak_days,
        }


def build_recent_reality_window(
    *,
    today: date,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
) -> RecentRealityWindow:
    start = today - timedelta(days=6)
    relevant_sessions = [
        session
        for session in scheduled_sessions
        if (scheduled_date := _as_date(_value(session, "scheduled_date"))) is not None
        and start <= scheduled_date <= today
        and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
    ]
    relevant_activities = [
        activity
        for activity in activities
        if (activity_date := _as_date(_value(activity, "started_at") or _value(activity, "created_at"))) is not None
        and start <= activity_date <= today
    ]

    evaluated_sessions: list[tuple[Any, Any]] = []
    for session in relevant_sessions:
        evidence = classify_execution_evidence(planned_session=session, activities=relevant_activities)
        session_date = _as_date(_value(session, "scheduled_date"))
        if session_date == today and evidence.display_status != "confirmed_done":
            continue
        evaluated_sessions.append((session, evidence))

    confirmed_sessions = 0
    key_sessions_salvaged = 0
    for session, evidence in evaluated_sessions:
        if evidence.display_status != "confirmed_done":
            continue
        confirmed_sessions += 1
        if _is_key_session(session):
            key_sessions_salvaged += 1

    filtered_sessions = [session for session, _ in evaluated_sessions]
    planned_sessions = len(filtered_sessions)
    planned_tss = round(sum(estimate_scheduled_session_tss(session) for session in filtered_sessions), 1)
    observed_tss = round(sum(float(_value(activity, "tss") or 0.0) for activity in relevant_activities), 1)

    return RecentRealityWindow(
        planned_sessions_7d=planned_sessions,
        confirmed_sessions_7d=confirmed_sessions,
        claimed_sessions_7d=0,
        key_sessions_salvaged_7d=key_sessions_salvaged,
        planned_tss_7d=planned_tss,
        observed_tss_7d=observed_tss,
        compliance_confirmed=_compliance_confirmed(planned_sessions=planned_sessions, confirmed_sessions=confirmed_sessions),
        load_ratio=_load_ratio(planned_tss=planned_tss, observed_tss=observed_tss),
        missed_streak_days=_missed_streak_days(today=today, sessions=filtered_sessions, activities=relevant_activities),
    )


def _compliance_confirmed(*, planned_sessions: int, confirmed_sessions: int) -> float:
    if planned_sessions <= 0:
        return 1.0
    return round(confirmed_sessions / planned_sessions, 2)


def _load_ratio(*, planned_tss: float, observed_tss: float) -> float:
    if planned_tss <= 0:
        return 1.0
    return round(observed_tss / planned_tss, 2)


def _missed_streak_days(*, today: date, sessions: Sequence[Any], activities: Sequence[Any]) -> int:
    streak = 0
    cursor = today - timedelta(days=1)
    window_start = today - timedelta(days=6)

    while cursor >= window_start:
        day_sessions = [
            session
            for session in sessions
            if _as_date(_value(session, "scheduled_date")) == cursor
            and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
        ]
        if not day_sessions:
            cursor -= timedelta(days=1)
            continue
        if any(
            classify_execution_evidence(planned_session=session, activities=activities).display_status == "confirmed_done"
            for session in day_sessions
        ):
            break
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").strip().lower()
    if priority in KEY_PRIORITIES:
        return True
    load_score = _int(_value(session, "load_score")) or 0
    return load_score >= 3


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


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
