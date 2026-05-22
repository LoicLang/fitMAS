from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import pow
from typing import Any


def estimate_tss(activity: Any, user: Any | None = None) -> float | None:
    sport_type = str(_value(activity, "sport_type") or "").lower()
    duration_min = _float(_value(activity, "duration_min"))
    perceived_load = _float(_value(activity, "perceived_load"))
    avg_hr = _float(_value(activity, "avg_hr"))

    if not duration_min or duration_min <= 0:
        return None

    if sport_type in {"running", "cycling"} and avg_hr and avg_hr > 0:
        age = _float(_value(user, "age")) or 31
        estimated_max_hr = max(160.0, 208.0 - (0.7 * age))
        hr_ratio = min(1.1, avg_hr / estimated_max_hr)
        return round(duration_min * pow(hr_ratio, 2) * 1.2, 1)

    if perceived_load and perceived_load > 0:
        return round((duration_min * perceived_load) / 6.0, 1)

    fallback_rpe = {
        "running": 5.0,
        "cycling": 5.0,
        "swimming": 5.5,
        "climbing": 6.0,
        "strength": 6.0,
    }.get(sport_type)
    if fallback_rpe:
        return round((duration_min * fallback_rpe) / 6.0, 1)

    return None


def compute_ctl_atl_tsb(
    activities: list[Any],
    as_of_date: date | datetime | None = None,
    *,
    ctl_days: int = 42,
    atl_days: int = 7,
    lookback_days: int = 84,
) -> dict[str, Any]:
    end_date = _as_date(as_of_date) or _latest_activity_date(activities) or date.today()
    start_date = end_date - timedelta(days=max(lookback_days - 1, ctl_days * 2))

    daily_tss: dict[date, float] = defaultdict(float)
    for activity in activities:
        activity_date = _as_date(_value(activity, "started_at") or _value(activity, "created_at"))
        if activity_date is None or activity_date < start_date or activity_date > end_date:
            continue
        tss = _float(_value(activity, "tss"))
        if tss is None:
            continue
        daily_tss[activity_date] += tss

    ctl = 0.0
    atl = 0.0
    ctl_alpha = 2 / (ctl_days + 1)
    atl_alpha = 2 / (atl_days + 1)
    series: list[dict[str, float | str]] = []

    current = start_date
    while current <= end_date:
        day_tss = round(daily_tss.get(current, 0.0), 1)
        ctl = (day_tss * ctl_alpha) + (ctl * (1 - ctl_alpha))
        atl = (day_tss * atl_alpha) + (atl * (1 - atl_alpha))
        tsb = ctl - atl
        series.append(
            {
                "date": current.isoformat(),
                "tss": day_tss,
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
            }
        )
        current += timedelta(days=1)

    latest = series[-1] if series else {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
    return {
        "as_of_date": end_date.isoformat(),
        "ctl": latest["ctl"],
        "atl": latest["atl"],
        "tsb": latest["tsb"],
        "series": series,
    }


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


def _latest_activity_date(activities: list[Any]) -> date | None:
    dates = [
        activity_date
        for activity in activities
        if (activity_date := _as_date(_value(activity, "started_at") or _value(activity, "created_at")))
    ]
    return max(dates) if dates else None
