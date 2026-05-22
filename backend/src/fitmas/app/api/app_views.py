from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fitmas.calendar_resolution import build_session_item, resolve_calendar_payload
from fitmas.domain.athlete.fitness_snapshot import estimate_scheduled_session_tss
from fitmas.domain.athlete.load_projection import build_load_forecast, planning_mode_label_fr
from fitmas.workout_content import build_workout_content
from fitmas.time_context import get_local_now

_DAY_LABELS_FR_SHORT = {0: "Lun", 1: "Mar", 2: "Mer", 3: "Jeu", 4: "Ven", 5: "Sam", 6: "Dim"}

REST_SPORTS = {"rest", "off"}


def build_app_overview(
    *,
    today_date: date,
    profile: Any,
    strava_status: dict[str, Any],
    scheduled_sessions: list[Any],
    activities: list[Any],
    performance_overview: dict[str, Any],
    today_view: dict[str, Any] | None,
    session_policies: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    session_policy_by_id = {int(_value(policy, "session_id") or 0): policy for policy in session_policies}
    visible_sessions = [session for session in scheduled_sessions if str(_value(session, "sport_type") or "").lower() not in REST_SPORTS]

    # Check if today is a rest/flexible day
    today_is_rest = any(
        str(_value(session, "sport_type") or "").lower() in REST_SPORTS
        and _as_date(_value(session, "scheduled_date")) == today_date
        for session in scheduled_sessions
    )

    lead_session = None
    if today_view is not None:
        lead_session = next((session for session in visible_sessions if int(_value(session, "id") or 0) == int(today_view.get("scheduled_session_id") or 0)), None)
    if lead_session is None and not today_is_rest:
        # Only fall through to the next future session if today is NOT a rest day.
        # On rest days we show no lead session rather than jumping to tomorrow.
        lead_session = next((session for session in visible_sessions if (_as_date(_value(session, "scheduled_date")) or today_date) >= today_date), None)
    if lead_session is None and visible_sessions and not today_is_rest:
        lead_session = visible_sessions[0]

    activity_by_session = _activity_map_by_session(activities)
    lead_card = (
        build_session_item(
            lead_session,
            activity_by_session.get(int(_value(lead_session, "id") or 0), []),
            today=today_date,
            session_policy=session_policy_by_id.get(int(_value(lead_session, "id") or 0)),
        )
        if lead_session
        else None
    )

    # On rest days, show upcoming starting from tomorrow
    upcoming_start = today_date + timedelta(days=1) if today_is_rest else today_date
    upcoming = [
        build_session_item(
            session,
            activity_by_session.get(int(_value(session, "id") or 0), []),
            today=today_date,
            session_policy=session_policy_by_id.get(int(_value(session, "id") or 0)),
        )
        for session in visible_sessions
        if (_as_date(_value(session, "scheduled_date")) or today_date) >= upcoming_start
    ][:5]

    weekly_hours = round(sum((_float(_value(session, "duration_min")) or 0.0) for session in visible_sessions if _same_week(_value(session, "scheduled_date"), today_date)) / 60.0, 1)

    return {
        "today": today_view,
        "today_is_rest": today_is_rest,
        "lead_session": lead_card,
        "upcoming_sessions": upcoming,
        "week": performance_overview.get("week", {}),
        "load": performance_overview.get("load", {}),
        "tss": performance_overview.get("tss", {}),
        "completion": performance_overview.get("completion", {}),
        "recent_reality": performance_overview.get("recent_reality", {}),
        "weekly_hours": weekly_hours,
        "profile": {
            "name": _value(profile, "name"),
            "coach_name": _value(profile, "coach_name"),
            "objective": _value(profile, "objective") or _value(profile, "primary_objective"),
            "sports": list(_value(profile, "sports") or ()),
            "constraints": list(_value(profile, "constraints") or ()),
            "preferences": list(_value(profile, "preferences") or ()),
        },
        "strava": strava_status,
    }


def build_app_calendar(
    *,
    today_date: date,
    month_start: date,
    scheduled_sessions: list[Any],
    activities: list[Any],
    performance_overview: dict[str, Any],
    session_policies: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    policy_by_id = {int(_value(policy, "session_id") or 0): policy for policy in session_policies}
    resolved = resolve_calendar_payload(scheduled_sessions=scheduled_sessions, activities=activities, today=today_date)
    enriched_sessions = [
        {
            **item,
            "role": str(_value(policy_by_id.get(int(item.get("id") or 0)), "role") or item.get("role") or ""),
            "confidence": str(_value(policy_by_id.get(int(item.get("id") or 0)), "confidence") or item.get("confidence") or ""),
        }
        for item in resolved["sessions"]
    ]
    day_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in enriched_sessions + resolved["offplan"]:
        if item["display_date"]:
            day_items[item["display_date"]].append(item)

    month_grid = []
    start = month_start - timedelta(days=month_start.weekday())
    end_of_month = _end_of_month(month_start)
    end = end_of_month + timedelta(days=(6 - end_of_month.weekday()))
    cursor = start
    while cursor <= end:
        iso = cursor.isoformat()
        month_grid.append(
            {
                "date": iso,
                "day_number": cursor.day,
                "in_month": cursor.month == month_start.month,
                "is_today": cursor == today_date,
                "is_current_week": _same_week(cursor, today_date),
                "items": sorted(day_items.get(iso, []), key=lambda item: (item["kind"], item["title"])),
            }
        )
        cursor += timedelta(days=1)

    feed = sorted(
        [item for item in enriched_sessions + resolved["offplan"] if item["display_date"] and item["display_date"].startswith(month_start.isoformat()[:7])],
        key=lambda item: ((item["display_date"] or ""), item["title"]),
    )

    return {
        "month": {
            "key": month_start.isoformat()[:7],
            "label": month_start.strftime("%Y-%m"),
            "week_label": performance_overview.get("week", {}).get("label", ""),
            "mesocycle_week": performance_overview.get("week", {}).get("mesocycle_week", 1),
            "mesocycle_number": performance_overview.get("week", {}).get("mesocycle_number", 1),
            "is_deload": performance_overview.get("week", {}).get("is_deload", False),
        },
        "days": month_grid,
        "feed": feed,
    }


def build_app_evolution(
    *,
    today_date: date,
    scheduled_sessions: list[Any],
    activities: list[Any],
    performance_overview: dict[str, Any],
    training_load: dict[str, Any],
) -> dict[str, Any]:
    history = [
        {
            "date": point.get("date"),
            "ctl": round(float(point.get("ctl") or 0.0), 1),
            "atl": round(float(point.get("atl") or 0.0), 1),
            "tsb": round(float(point.get("tsb") or 0.0), 1),
        }
        for point in list(training_load.get("series") or [])[-28:]
    ]
    week_daily = _build_week_daily(today_date=today_date, scheduled_sessions=scheduled_sessions, activities=activities)
    load = performance_overview.get("load", {})
    week = performance_overview.get("week", {})
    current_target = float(performance_overview.get("tss", {}).get("target") or performance_overview.get("tss", {}).get("planned_this_week") or 0.0)
    forecast = [
        {
            "week_index": item.week_index,
            "cycle_week": item.cycle_week,
            "target_tss": item.target_tss,
            "projected_ctl": item.projected_ctl,
            "focus": item.focus,
            "planning_mode": planning_mode_label_fr(item.planning_mode),
            "is_deload": item.is_deload,
        }
        for item in build_load_forecast(
            current_ctl=float(load.get("ctl") or 0.0),
            current_target_tss=current_target,
            current_cycle_week=int(week.get("mesocycle_week") or 1),
            planning_mode=str(week.get("planning_mode") or "maintain_load"),
        )
    ]

    return {
        "week": week,
        "load": load,
        "tss": performance_overview.get("tss", {}),
        "completion": performance_overview.get("completion", {}),
        "recent_reality": performance_overview.get("recent_reality", {}),
        "distribution": performance_overview.get("distribution", {}),
        "sports": performance_overview.get("sports", {}),
        "rationale": performance_overview.get("rationale", []),
        "risk_flags": performance_overview.get("risk_flags", []),
        "history": history,
        "week_daily": week_daily,
        "forecast": forecast,
    }


def build_session_detail(
    *,
    today_date: date,
    session: Any,
    linked_activity: Any | None,
    fitness: dict[str, Any] | None,
    recent_activity: dict[str, Any] | None,
    change_notes: list[dict[str, Any]],
    watch_items: list[dict[str, Any]],
    recent_reality: dict[str, Any] | None = None,
    active_facts: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    surrounding_sessions: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    resolved_session = build_session_item(session, [linked_activity] if linked_activity else [], today=today_date)
    sport = str(_value(session, "sport_type") or "").lower()
    content = build_workout_content(
        session,
        watch_items=watch_items,
        recent_reality=recent_reality,
        active_facts=active_facts,
        surrounding_sessions=surrounding_sessions,
    )
    distance_m = _float(_value(linked_activity, "distance_m"))
    duration_min = _float(_value(linked_activity, "duration_min")) or _float(_value(session, "duration_min"))
    avg_speed = _float(_value(linked_activity, "avg_speed"))
    # Elevation is irrelevant for swimming and strength
    elevation_m = _float(_value(linked_activity, "elevation_m")) if sport not in {"swimming", "strength"} else None
    detail = {
        "session": resolved_session,
        "metrics": {
            "distance_m": distance_m,
            "duration_min": duration_min,
            "elevation_m": elevation_m,
            "avg_hr": _float(_value(linked_activity, "avg_hr")),
            "avg_speed": avg_speed,
            "tss": _float(_value(linked_activity, "tss")) or round(estimate_scheduled_session_tss(session), 1),
        },
        "linked_activity": linked_activity,
        "fitness": fitness,
        "recent_activity": recent_activity,
        "coach": {
            "goal": _value(session, "session_goal") or "",
            "note": _value(session, "session_note") or "",
            "description": _value(session, "session_description") or "",
            "nutrition_focus": _value(session, "nutrition_focus") or "",
            "change_notes": change_notes,
            "watch_items": watch_items,
        },
        "content": content.as_dict(),
        "zone_distribution": _zone_distribution(_value(session, "load_band")),
        "map_polyline": _value(linked_activity, "map_polyline"),
    }
    return detail


def _build_week_daily(
    *,
    today_date: date,
    scheduled_sessions: list[Any],
    activities: list[Any],
) -> list[dict[str, Any]]:
    week_start = today_date - timedelta(days=today_date.weekday())
    session_map: dict[date, list[Any]] = defaultdict(list)
    activity_map: dict[date, list[Any]] = defaultdict(list)

    for session in scheduled_sessions:
        session_date = _as_date(_value(session, "scheduled_date"))
        if session_date is None:
            continue
        if week_start <= session_date <= week_start + timedelta(days=6):
            session_map[session_date].append(session)

    for activity in activities:
        activity_date = _as_date(_value(activity, "started_at") or _value(activity, "created_at"))
        if activity_date is None:
            continue
        if week_start <= activity_date <= week_start + timedelta(days=6):
            activity_map[activity_date].append(activity)

    rows = []
    for offset in range(7):
        current = week_start + timedelta(days=offset)
        planned_sessions = [session for session in session_map.get(current, []) if str(_value(session, "sport_type") or "").lower() not in REST_SPORTS]
        actual_activities = activity_map.get(current, [])
        rows.append(
            {
                "date": current.isoformat(),
                "label": _DAY_LABELS_FR_SHORT.get(current.weekday(), current.strftime("%a")),
                "planned_tss": round(sum(estimate_scheduled_session_tss(session) for session in planned_sessions), 1),
                "actual_tss": round(sum(_float(_value(activity, "tss")) or 0.0 for activity in actual_activities), 1),
                "planned_duration_min": int(sum(_float(_value(session, "duration_min")) or 0.0 for session in planned_sessions)),
                "actual_duration_min": int(sum(_float(_value(activity, "duration_min")) or 0.0 for activity in actual_activities)),
            }
        )
    return rows


def _activity_map_by_session(activities: list[Any]) -> dict[int, list[Any]]:
    mapping: dict[int, list[Any]] = defaultdict(list)
    for activity in activities:
        session_id = _value(activity, "scheduled_session_id")
        if session_id is None:
            continue
        mapping[int(session_id)].append(activity)
    return mapping


def _zone_distribution(load_band: Any) -> list[int]:
    table = {
        "hard": [5, 15, 22, 38, 20],
        "moderate": [12, 34, 24, 18, 12],
        "easy": [24, 48, 20, 6, 2],
        "recovery": [52, 34, 12, 2, 0],
        "mobility": [68, 20, 10, 2, 0],
    }
    return table.get(str(load_band or "easy"), table["easy"])


def _same_week(value: Any, anchor: date) -> bool:
    current = _as_date(value)
    if current is None:
        return False
    week_start = anchor - timedelta(days=anchor.weekday())
    return week_start <= current <= week_start + timedelta(days=6)


def _end_of_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1) - timedelta(days=1)
    return date(value.year, value.month + 1, 1) - timedelta(days=1)


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
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
