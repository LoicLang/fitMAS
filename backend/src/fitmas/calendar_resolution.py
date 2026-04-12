from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

REST_SPORTS = {"rest", "off"}


def resolve_calendar_payload(
    *,
    scheduled_sessions: list[Any],
    activities: list[Any],
    today: date,
) -> dict[str, list[dict[str, Any]]]:
    sessions_by_id = {int(_value(session, "id")): session for session in scheduled_sessions if _value(session, "id") is not None}
    linked_activities: dict[int, list[Any]] = defaultdict(list)
    offplan_items: list[dict[str, Any]] = []

    for activity in activities:
        session_id = _value(activity, "scheduled_session_id")
        if session_id is not None:
            linked_activities[int(session_id)].append(activity)
        if _is_offplan_activity(activity, sessions_by_id):
            offplan_items.append(build_offplan_item(activity))

    session_items = [build_session_item(session, linked_activities.get(int(_value(session, "id") or 0), []), today=today) for session in scheduled_sessions]
    return {
        "sessions": session_items,
        "offplan": sorted(offplan_items, key=lambda item: (item["display_date"], item["id"])),
    }


def build_session_item(
    session: Any,
    linked_activities: list[Any],
    *,
    today: date,
    session_policy: Any | None = None,
) -> dict[str, Any]:
    sport_type = str(_value(session, "sport_type") or "").lower()
    scheduled_date = _as_date(_value(session, "scheduled_date"))
    raw_status = str(_value(session, "completion_status") or "planned").lower()
    valid_activity = _pick_valid_activity(session, linked_activities)
    invalid_linked = [activity for activity in linked_activities if activity is not valid_activity]

    status = "planned"
    if raw_status == "done" and valid_activity is not None:
        status = "done"
    elif scheduled_date is not None and scheduled_date < today and sport_type not in REST_SPORTS:
        status = "missing"
    elif raw_status == "adapted":
        status = "adapted"

    executed_date = _date_to_iso(_as_date(_value(valid_activity, "started_at") or _value(valid_activity, "created_at")))
    display_date = executed_date or _date_to_iso(scheduled_date)

    return {
        "kind": "session",
        "id": int(_value(session, "id") or 0),
        "status": status,
        "scheduled_date": _date_to_iso(scheduled_date),
        "display_date": display_date,
        "executed_date": executed_date,
        "day": str(_value(session, "day") or ""),
        "label": str(_value(session, "label") or ""),
        "title": str(_value(session, "session_title") or ""),
        "goal": str(_value(session, "session_goal") or ""),
        "description": str(_value(session, "session_description") or ""),
        "sport_type": sport_type,
        "session_type": str(_value(session, "session_type") or ""),
        "duration_min": _int(_value(session, "duration_min")),
        "load_band": _load_band(session),
        "priority": str(_value(session, "priority") or ""),
        "role": str(_value(session_policy, "role") or ""),
        "confidence": str(_value(session_policy, "confidence") or ""),
        "linked_activity_id": _int(_value(valid_activity, "id")),
        "linked_activity_title": str(_value(valid_activity, "title") or "") or None,
        "has_invalid_linked_activity": bool(invalid_linked),
        "completion_status": raw_status,
    }


def build_offplan_item(activity: Any) -> dict[str, Any]:
    activity_date = _date_to_iso(_as_date(_value(activity, "started_at") or _value(activity, "created_at")))
    return {
        "kind": "offplan",
        "id": int(_value(activity, "id") or 0),
        "status": "offplan",
        "scheduled_date": None,
        "display_date": activity_date,
        "executed_date": activity_date,
        "day": "",
        "label": "Hors plan",
        "title": str(_value(activity, "title") or "Activité hors plan"),
        "goal": str(_value(activity, "note") or ""),
        "description": str(_value(activity, "source") or ""),
        "sport_type": str(_value(activity, "sport_type") or ""),
        "session_type": "offplan",
        "duration_min": _int(_value(activity, "duration_min")),
        "load_band": _activity_load_band(activity),
        "priority": "Off plan",
        "linked_activity_id": int(_value(activity, "id") or 0),
        "linked_activity_title": str(_value(activity, "title") or "") or None,
        "has_invalid_linked_activity": False,
        "completion_status": "offplan",
    }


def _is_offplan_activity(activity: Any, sessions_by_id: dict[int, Any]) -> bool:
    session_id = _value(activity, "scheduled_session_id")
    if session_id is None:
        return True
    session = sessions_by_id.get(int(session_id))
    if session is None:
        return True
    return str(_value(activity, "sport_type") or "").lower() != str(_value(session, "sport_type") or "").lower()


def _pick_valid_activity(session: Any, activities: list[Any]) -> Any | None:
    session_sport = str(_value(session, "sport_type") or "").lower()
    for activity in activities:
        if str(_value(activity, "sport_type") or "").lower() == session_sport:
            return activity
    return None


def _load_band(session: Any) -> str | None:
    value = _value(session, "load_band")
    return str(value) if value else None


def _activity_load_band(activity: Any) -> str:
    perceived = _int(_value(activity, "perceived_load")) or 2
    if perceived >= 5:
        return "hard"
    if perceived >= 4:
        return "moderate"
    if perceived <= 1:
        return "recovery"
    return "easy"


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


def _date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
