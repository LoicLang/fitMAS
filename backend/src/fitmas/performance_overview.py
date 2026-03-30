from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fitmas.fitness_snapshot import build_fitness_snapshot, estimate_scheduled_session_tss
from fitmas.load_projection import planning_mode_label_fr
from fitmas.models import WeeklyPlan
from fitmas.recent_reality import build_recent_reality_window
from fitmas.session_metadata import compute_load_band
from fitmas.time_context import get_local_now

LOAD_BANDS = ("hard", "moderate", "easy", "recovery", "mobility")


def build_performance_overview(
    *,
    user_id: int,
    timezone_name: str | None,
    activities: list[Any],
    scheduled_sessions: list[Any],
    week_plan: WeeklyPlan,
    planning_decision: Any | None,
) -> dict[str, Any]:
    today = get_local_now(timezone_name).date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    week_sessions = [
        session
        for session in scheduled_sessions
        if (session_date := _as_date(_value(session, "scheduled_date"))) is not None
        and week_start <= session_date <= week_end
    ]
    week_activities = [
        activity
        for activity in activities
        if (activity_date := _as_date(_value(activity, "started_at") or _value(activity, "created_at"))) is not None
        and week_start <= activity_date <= week_end
    ]

    snapshot = build_fitness_snapshot(
        user_id=user_id,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        as_of_date=today,
    )
    recent_reality = build_recent_reality_window(
        today=today,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    planned_distribution = _planned_distribution(week_sessions)
    completed_distribution = _completed_distribution(week_sessions)

    target_tss = round(snapshot.weekly_target_tss, 1)
    actual_tss = round(snapshot.weekly_actual_tss, 1)
    remaining_tss = round(max(target_tss - actual_tss, 0.0), 1)

    return {
        "week": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "label": week_plan.week_label,
            "mesocycle_week": week_plan.mesocycle_week,
            "mesocycle_number": week_plan.mesocycle_number,
            "is_deload": week_plan.is_deload,
            "planning_mode": planning_mode_label_fr(str(_value(planning_decision, "planning_mode") or "maintain_load")),
            "adaptation_level": _value(planning_decision, "adaptation_level"),
            "adaptation_scope": _value(planning_decision, "adaptation_scope"),
            "intensity_distribution": _value(planning_decision, "intensity_distribution"),
        },
        "load": {
            "ctl": round(snapshot.ctl, 1),
            "atl": round(snapshot.atl, 1),
            "tsb": round(snapshot.tsb, 1),
            "ramp_rate": round(snapshot.ramp_rate, 2),
            "freshness": _freshness(snapshot.tsb),
        },
        "tss": {
            "target": target_tss,
            "actual": actual_tss,
            "remaining": remaining_tss,
            "delta": round(actual_tss - target_tss, 1),
            "planned_this_week": round(sum(estimate_scheduled_session_tss(session) for session in week_sessions), 1),
            "actual_activities_this_week": round(sum(float(_value(activity, "tss") or 0.0) for activity in week_activities), 1),
        },
        "completion": {
            "rate_14d": snapshot.completion_rate_14d,
            "key_sessions_done_14d": snapshot.key_sessions_done_14d,
            "volume_sessions_done_14d": snapshot.volume_sessions_done_14d,
            "sessions_this_week": len([session for session in week_sessions if str(_value(session, "sport_type") or "").lower() not in {"rest", "off"}]),
            "done_this_week": len([session for session in week_sessions if str(_value(session, "completion_status") or "").lower() == "done"]),
        },
        "recent_reality": recent_reality.as_dict(),
        "distribution": {
            "planned": planned_distribution,
            "completed": completed_distribution,
        },
        "sports": {
            "ctl": snapshot.sport_ctl,
            "volume_hours_14d": snapshot.sport_volume_hours,
        },
        "rationale": list(_value(planning_decision, "rationale") or ()),
        "risk_flags": list(_value(planning_decision, "risk_flags") or ()),
    }


def _planned_distribution(week_sessions: list[Any]) -> dict[str, dict[str, float | int]]:
    buckets = _empty_distribution()
    for session in week_sessions:
        sport = str(_value(session, "sport_type") or "").lower()
        if sport in {"rest", "off"}:
            continue
        load_band = _session_load_band(session)
        buckets[load_band]["count"] += 1
        buckets[load_band]["tss"] = round(buckets[load_band]["tss"] + estimate_scheduled_session_tss(session), 1)
    return buckets


def _completed_distribution(week_sessions: list[Any]) -> dict[str, dict[str, float | int]]:
    buckets = _empty_distribution()
    for session in week_sessions:
        if str(_value(session, "completion_status") or "").lower() != "done":
            continue
        sport = str(_value(session, "sport_type") or "").lower()
        if sport in {"rest", "off"}:
            continue
        load_band = _session_load_band(session)
        buckets[load_band]["count"] += 1
        actual_tss = _linked_activity_tss(session)
        if actual_tss is None:
            actual_tss = estimate_scheduled_session_tss(session)
        buckets[load_band]["tss"] = round(buckets[load_band]["tss"] + actual_tss, 1)
    return buckets


def _empty_distribution() -> dict[str, dict[str, float | int]]:
    return {band: {"count": 0, "tss": 0.0} for band in LOAD_BANDS}


def _session_load_band(session: Any) -> str:
    return compute_load_band(
        sport_type=str(_value(session, "sport_type") or ""),
        session_type=str(_value(session, "session_type") or ""),
        intensity=str(_value(session, "intensity") or ""),
        load_score=int(_value(session, "load_score") or 0),
    )


def _linked_activity_tss(session: Any) -> float | None:
    activities = _value(session, "activities") or []
    valid_tss = [float(_value(activity, "tss") or 0.0) for activity in activities if _value(activity, "tss") is not None]
    if not valid_tss:
        return None
    return round(max(valid_tss), 1)


def _freshness(tsb: float) -> str:
    if tsb >= 5:
        return "frais"
    if tsb < -10:
        return "fatigué"
    return "stable"


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
