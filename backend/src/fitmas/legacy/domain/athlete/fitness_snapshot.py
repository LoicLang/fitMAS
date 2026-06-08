from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from fitmas.legacy.domain.planning.planning_config import SUPPORTED_SPORTS, get_sport_planning_config
from fitmas.legacy.domain.athlete.training_load import compute_ctl_atl_tsb

DONE_SESSION_STATUSES = {"done"}
KEY_PRIORITIES = {"high", "key", "important"}
HIGH_INTENSITIES = {"moderate", "hard", "tempo"}
REST_SPORTS = {"rest", "off"}


@dataclass(frozen=True, slots=True)
class FitnessSnapshot:
    user_id: int
    date: date
    ctl: float
    atl: float
    tsb: float
    ramp_rate: float
    weekly_target_tss: float
    weekly_actual_tss: float
    completion_rate_14d: float
    key_sessions_done_14d: int
    volume_sessions_done_14d: int
    sport_ctl: dict[str, float]
    sport_volume_hours: dict[str, float]


def build_fitness_snapshot(
    *,
    user_id: int,
    activities: Sequence[Any],
    scheduled_sessions: Sequence[Any] | None = None,
    as_of_date: date | datetime | None = None,
) -> FitnessSnapshot:
    snapshot_date = _as_date(as_of_date) or _latest_activity_date(activities) or date.today()
    load = compute_ctl_atl_tsb(list(activities), as_of_date=snapshot_date)
    week_start = snapshot_date - timedelta(days=snapshot_date.weekday())
    week_end = week_start + timedelta(days=6)
    trailing_14_start = snapshot_date - timedelta(days=13)

    weekly_actual_tss = round(_sum_activity_tss(activities, start=week_start, end=week_end), 1)
    weekly_target_tss = round(
        _sum_scheduled_target_tss(scheduled_sessions or [], start=week_start, end=week_end),
        1,
    )
    completion_rate_14d, key_sessions_done_14d, volume_sessions_done_14d = _completion_metrics(
        scheduled_sessions or [],
        start=trailing_14_start,
        end=snapshot_date,
    )
    sport_ctl = {
        sport: round(
            float(compute_ctl_atl_tsb(_filter_activities_by_sport(activities, sport), as_of_date=snapshot_date)["ctl"]),
            1,
        )
        for sport in SUPPORTED_SPORTS
    }
    sport_volume_hours = {
        sport: round(
            _sum_activity_duration(activities, sport=sport, start=trailing_14_start, end=snapshot_date) / 60.0,
            1,
        )
        for sport in SUPPORTED_SPORTS
    }

    return FitnessSnapshot(
        user_id=user_id,
        date=snapshot_date,
        ctl=float(load["ctl"]),
        atl=float(load["atl"]),
        tsb=float(load["tsb"]),
        ramp_rate=_compute_ramp_rate(activities, snapshot_date=snapshot_date),
        weekly_target_tss=weekly_target_tss,
        weekly_actual_tss=weekly_actual_tss,
        completion_rate_14d=completion_rate_14d,
        key_sessions_done_14d=key_sessions_done_14d,
        volume_sessions_done_14d=volume_sessions_done_14d,
        sport_ctl=sport_ctl,
        sport_volume_hours=sport_volume_hours,
    )


def estimate_scheduled_session_tss(session: Any) -> float:
    sport = str(_value(session, "sport_type") or "").lower()
    if sport in REST_SPORTS:
        return 0.0
    duration_min = _int(_value(session, "duration_min"))
    if not duration_min or duration_min <= 0:
        return 0.0
    config = get_sport_planning_config(sport)
    base_tss = (duration_min / 60.0) * config.default_tss_per_hour
    intensity = str(_value(session, "intensity") or "").lower()
    multiplier = 1.0
    if intensity in {"recovery", "easy"}:
        multiplier = 0.85
    elif intensity in HIGH_INTENSITIES:
        multiplier = 1.15
    return round(base_tss * multiplier, 1)


def _completion_metrics(
    sessions: Sequence[Any],
    *,
    start: date,
    end: date,
) -> tuple[float, int, int]:
    relevant = [
        session
        for session in sessions
        if (scheduled_date := _scheduled_date(session)) is not None
        and start <= scheduled_date <= end
        and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
    ]
    if not relevant:
        return 0.0, 0, 0

    done = [session for session in relevant if str(_value(session, "completion_status") or "").lower() in DONE_SESSION_STATUSES]
    key_done = sum(1 for session in done if _is_key_session(session))
    volume_done = sum(1 for session in done if not _is_key_session(session))
    completion_rate = round(len(done) / len(relevant), 2)
    return completion_rate, key_done, volume_done


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").strip().lower()
    if priority in KEY_PRIORITIES:
        return True
    load_score = _int(_value(session, "load_score")) or 0
    if load_score >= 3:
        return True
    intensity = str(_value(session, "intensity") or "").lower()
    return intensity in HIGH_INTENSITIES


def _sum_scheduled_target_tss(sessions: Sequence[Any], *, start: date, end: date) -> float:
    total = 0.0
    for session in sessions:
        scheduled_date = _scheduled_date(session)
        if scheduled_date is None or scheduled_date < start or scheduled_date > end:
            continue
        total += estimate_scheduled_session_tss(session)
    return total


def _sum_activity_tss(activities: Sequence[Any], *, start: date, end: date) -> float:
    total = 0.0
    for activity in activities:
        activity_date = _activity_date(activity)
        if activity_date is None or activity_date < start or activity_date > end:
            continue
        total += float(_value(activity, "tss") or 0.0)
    return total


def _sum_activity_duration(
    activities: Sequence[Any],
    *,
    sport: str,
    start: date,
    end: date,
) -> float:
    total = 0.0
    for activity in activities:
        if str(_value(activity, "sport_type") or "").lower() != sport:
            continue
        activity_date = _activity_date(activity)
        if activity_date is None or activity_date < start or activity_date > end:
            continue
        total += float(_value(activity, "duration_min") or 0.0)
    return total


def _compute_ramp_rate(activities: Sequence[Any], *, snapshot_date: date) -> float:
    current_week_start = snapshot_date - timedelta(days=snapshot_date.weekday())
    previous_week_start = current_week_start - timedelta(days=7)
    previous_week_end = current_week_start - timedelta(days=1)
    current_week_end = current_week_start + timedelta(days=6)

    current_tss = _sum_activity_tss(activities, start=current_week_start, end=min(snapshot_date, current_week_end))
    previous_tss = _sum_activity_tss(activities, start=previous_week_start, end=previous_week_end)
    if previous_tss <= 0:
        return 0.0 if current_tss <= 0 else 1.0
    return round((current_tss - previous_tss) / previous_tss, 2)


def _filter_activities_by_sport(activities: Iterable[Any], sport: str) -> list[Any]:
    return [activity for activity in activities if str(_value(activity, "sport_type") or "").lower() == sport]


def _activity_date(activity: Any) -> date | None:
    return _as_date(_value(activity, "started_at") or _value(activity, "created_at"))


def _scheduled_date(session: Any) -> date | None:
    return _as_date(_value(session, "scheduled_date"))


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


def _latest_activity_date(activities: Sequence[Any]) -> date | None:
    dates = [activity_date for activity in activities if (activity_date := _activity_date(activity))]
    return max(dates) if dates else None
