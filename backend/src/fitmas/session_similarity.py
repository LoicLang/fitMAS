from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class SameSportProximityConflict:
    session_id: int
    sport_type: str
    session_type: str
    session_date: date
    target_date: date


def find_same_sport_proximity_conflict(
    *,
    target_session_id: int,
    target_date: date,
    scheduled_sessions: Sequence[Any],
    window_days: int = 2,
) -> SameSportProximityConflict | None:
    target_session = _find_session(scheduled_sessions, target_session_id)
    if target_session is None:
        return None
    target_sport = str(_value(target_session, "sport_type") or "").strip().lower()
    target_type = str(_value(target_session, "session_type") or "").strip().lower()
    if target_sport in {"", "rest", "off"} or not target_type:
        return None

    for session in scheduled_sessions:
        session_id = _value(session, "id")
        if session_id == target_session_id:
            continue
        if str(_value(session, "completion_status") or "").strip().lower() in {"done", "skipped"}:
            continue
        session_sport = str(_value(session, "sport_type") or "").strip().lower()
        session_type = str(_value(session, "session_type") or "").strip().lower()
        session_date = _as_date(_value(session, "scheduled_date"))
        if session_date is None:
            continue
        if session_sport != target_sport or session_type != target_type:
            continue
        if abs((session_date - target_date).days) <= window_days:
            return SameSportProximityConflict(
                session_id=int(session_id),
                sport_type=session_sport,
                session_type=session_type,
                session_date=session_date,
                target_date=target_date,
            )
    return None


def _find_session(sessions: Sequence[Any], session_id: int | None) -> Any | None:
    if session_id is None:
        return None
    for session in sessions:
        if _value(session, "id") == session_id:
            return session
    return None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
