from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fitmas.domain.athlete.training_load import compute_ctl_atl_tsb

SPORTS = ("running", "cycling", "swimming", "climbing", "strength")


def build_training_load_stats(
    activities: list[Any],
    *,
    as_of_date: date | datetime | None = None,
    weeks: int = 12,
) -> dict[str, Any]:
    stats = compute_ctl_atl_tsb(
        activities,
        as_of_date=as_of_date,
        lookback_days=max(weeks * 7, 84),
    )
    stats["series"] = stats["series"][-(weeks * 7) :]
    return stats


def build_volume_stats(
    activities: list[Any],
    *,
    as_of_date: date | datetime | None = None,
    weeks: int = 8,
) -> dict[str, Any]:
    end_date = _as_date(as_of_date) or _latest_activity_date(activities) or date.today()
    monday = end_date - timedelta(days=end_date.weekday())
    week_starts = [monday - timedelta(days=7 * offset) for offset in reversed(range(weeks))]
    buckets = {
        week_start: {
            "week_start": week_start.isoformat(),
            "running": {"duration_min": 0, "distance_m": 0.0, "tss": 0.0, "count": 0},
            "cycling": {"duration_min": 0, "distance_m": 0.0, "tss": 0.0, "count": 0},
            "swimming": {"duration_min": 0, "distance_m": 0.0, "tss": 0.0, "count": 0},
            "climbing": {"duration_min": 0, "distance_m": 0.0, "tss": 0.0, "count": 0},
            "strength": {"duration_min": 0, "distance_m": 0.0, "tss": 0.0, "count": 0},
        }
        for week_start in week_starts
    }

    for activity in activities:
        activity_date = _as_date(_value(activity, "started_at") or _value(activity, "created_at"))
        if activity_date is None:
            continue
        week_start = activity_date - timedelta(days=activity_date.weekday())
        bucket = buckets.get(week_start)
        if bucket is None:
            continue
        sport = str(_value(activity, "sport_type") or "").lower()
        if sport not in SPORTS:
            continue
        sport_bucket = bucket[sport]
        sport_bucket["duration_min"] += int(_value(activity, "duration_min") or 0)
        sport_bucket["distance_m"] += float(_value(activity, "distance_m") or 0.0)
        sport_bucket["tss"] += float(_value(activity, "tss") or 0.0)
        sport_bucket["count"] += 1

    weekly = []
    for week_start in week_starts:
        row = buckets[week_start]
        total_duration = sum(row[sport]["duration_min"] for sport in SPORTS)
        total_tss = round(sum(row[sport]["tss"] for sport in SPORTS), 1)
        weekly.append(
            {
                "week_start": row["week_start"],
                "sports": {
                    sport: {
                        "duration_min": row[sport]["duration_min"],
                        "distance_m": round(row[sport]["distance_m"], 1),
                        "tss": round(row[sport]["tss"], 1),
                        "count": row[sport]["count"],
                    }
                    for sport in SPORTS
                },
                "total_duration_min": total_duration,
                "total_tss": total_tss,
            }
        )
    return {"as_of_date": end_date.isoformat(), "weeks": weekly}


def build_records_stats(activities: list[Any]) -> dict[str, Any]:
    by_sport: dict[str, list[Any]] = defaultdict(list)
    for activity in activities:
        sport = str(_value(activity, "sport_type") or "").lower()
        if sport in SPORTS:
            by_sport[sport].append(activity)

    records = {}
    for sport, sport_activities in by_sport.items():
        longest_distance = _best_activity(sport_activities, "distance_m")
        longest_duration = _best_activity(sport_activities, "duration_min")
        max_elevation = _best_activity(sport_activities, "elevation_m")
        fastest = _fastest_activity(sport_activities, sport=sport)
        records[sport] = {
            "longest_distance_m": float(_value(longest_distance, "distance_m") or 0.0) if longest_distance else None,
            "longest_distance_activity_id": int(_value(longest_distance, "id")) if longest_distance else None,
            "longest_duration_min": int(_value(longest_duration, "duration_min") or 0) if longest_duration else None,
            "longest_duration_activity_id": int(_value(longest_duration, "id")) if longest_duration else None,
            "max_elevation_m": float(_value(max_elevation, "elevation_m") or 0.0) if max_elevation else None,
            "max_elevation_activity_id": int(_value(max_elevation, "id")) if max_elevation else None,
            "best_pace_seconds_per_km": _pace_seconds_per_km(fastest) if fastest else None,
            "best_pace_activity_id": int(_value(fastest, "id")) if fastest else None,
        }
    return {"sports": records}


def _best_activity(activities: list[Any], field: str) -> Any | None:
    valid = [activity for activity in activities if (_value(activity, field) or 0) > 0]
    if not valid:
        return None
    return max(valid, key=lambda activity: float(_value(activity, field) or 0.0))


def _fastest_activity(activities: list[Any], *, sport: str) -> Any | None:
    if sport not in {"running", "swimming", "cycling"}:
        return None
    valid = [activity for activity in activities if (_value(activity, "avg_speed") or 0) > 0 and (_value(activity, "distance_m") or 0) >= 1000]
    if not valid:
        return None
    return max(valid, key=lambda activity: float(_value(activity, "avg_speed") or 0.0))


def _pace_seconds_per_km(activity: Any | None) -> float | None:
    if activity is None:
        return None
    avg_speed = float(_value(activity, "avg_speed") or 0.0)
    if avg_speed <= 0:
        return None
    return round(1000.0 / avg_speed, 1)


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


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
