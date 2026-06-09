"""Read the V0 store (``v0_*`` tables) and produce the domain view-models the app
builders consume — used when ``FITMAS_APP_SOURCE=v0`` so the webapp shows the live V0
coach's plan instead of the legacy DB.

Reads the V0 sqlite directly (``FITMAS_V0_DB_PATH``); it does **not** import
``runtime_v0`` — the V0 core stays isolated, and the legacy app depends only on this
thin reader.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from fitmas.legacy.domain.execution.view_models import Activity
from fitmas.legacy.domain.planning.view_models import DayId, ScheduledSession

_DAY_BY_WEEKDAY = [
    DayId.MONDAY,
    DayId.TUESDAY,
    DayId.WEDNESDAY,
    DayId.THURSDAY,
    DayId.FRIDAY,
    DayId.SATURDAY,
    DayId.SUNDAY,
]

_TITLE = {
    "easy_run": "Footing facile",
    "long_run": "Sortie longue",
    "threshold": "Seuil",
    "intervals": "Intervalles",
    "recovery_run": "Récupération",
    "rest": "Repos",
}


def v0_db_path() -> Path:
    return Path(os.getenv("FITMAS_V0_DB_PATH", "fitmas_v0.db"))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def get_scheduled_sessions(user_id: int | None = None, limit: int = 120) -> list[ScheduledSession]:
    """Read the V0 calendar. The V0 store is solo (one user, keyed on the telegram
    chat id, not ``1``), so by default we don't filter by user_id."""
    path = v0_db_path()
    if not path.exists():
        return []
    with _connect(path) as conn:
        if user_id is None:
            rows = conn.execute(
                "select * from v0_scheduled_sessions order by date asc, id asc limit ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "select * from v0_scheduled_sessions where user_id = ? order by date asc, id asc limit ?",
                (user_id, limit),
            ).fetchall()
    sessions: list[ScheduledSession] = []
    for row in rows:
        day = date.fromisoformat(row["date"])
        title = row["title"] or _TITLE.get("", "")
        sessions.append(
            ScheduledSession(
                id=row["id"],
                day=_DAY_BY_WEEKDAY[day.weekday()],
                label=title,
                scheduled_date=row["date"],
                sport_type=row["sport"] or "running",
                session_title=title,
                session_goal="",
                duration_min=row["duration_min"],
                intensity=row["intensity_label"] or "easy",
                priority=row["priority"] or "secondary",
                completion_status=row["status"] or "planned",
            )
        )
    return sessions


def v0_user_id() -> int | None:
    """Resolve the single V0 user id (the store is solo)."""
    path = v0_db_path()
    if not path.exists():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "select user_id from v0_scheduled_sessions union select user_id from v0_activities limit 1"
        ).fetchone()
    return int(row["user_id"]) if row else None


def get_activities(user_id: int | None = None, limit: int = 500) -> list[Activity]:
    """Read the V0 activities. Solo store → default to no user_id filter (see above)."""
    path = v0_db_path()
    if not path.exists():
        return []
    with _connect(path) as conn:
        if user_id is None:
            rows = conn.execute(
                "select * from v0_activities order by date desc, id desc limit ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "select * from v0_activities where user_id = ? order by date desc, id desc limit ?",
                (user_id, limit),
            ).fetchall()
    activities: list[Activity] = []
    for row in rows:
        keys = row.keys()
        distance_km = row["distance_km"] if "distance_km" in keys else None
        sport = row["sport"] or "running"
        note = (row["notes"] if "notes" in keys else "") or ""
        duration_min = row["duration_min"]
        scheduled_session_id = row["scheduled_session_id"] if "scheduled_session_id" in keys else None
        # Rich Strava fields (present once the enriched sync has run; guarded for old DBs).
        avg_speed = row["avg_speed"] if "avg_speed" in keys else None
        avg_hr = row["avg_hr"] if "avg_hr" in keys else None
        elevation_m = row["elevation_m"] if "elevation_m" in keys else None
        calories = row["calories"] if "calories" in keys else None
        map_polyline = row["map_polyline"] if "map_polyline" in keys else None
        # The V0 store keeps duration but no per-activity load. Estimate a TSS proxy
        # from duration (~0.8 TSS/min, consistent with the session estimator) so the
        # training-load chart has signal. It is an estimate, not a measured TSS.
        tss = round(duration_min * 0.8, 1) if duration_min else None
        activities.append(
            Activity(
                id=row["id"],
                source=(row["source"] if "source" in keys else "v0") or "v0",
                sport_type=sport,
                title=note or _TITLE.get(sport, sport.capitalize()),
                duration_min=duration_min,
                distance_m=(float(distance_km) * 1000 if distance_km is not None else None),
                note=note,
                started_at=row["date"],
                tss=tss,
                perceived_load=int(tss) if tss else None,
                scheduled_session_id=scheduled_session_id,
                avg_speed=avg_speed,
                avg_hr=avg_hr,
                elevation_m=elevation_m,
                calories=calories,
                map_polyline=map_polyline,
            )
        )
    return activities
