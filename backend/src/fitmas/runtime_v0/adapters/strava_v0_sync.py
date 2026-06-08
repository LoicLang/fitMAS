"""Strava -> V0 activity sync (adapter; the legacy bridge).

Pulls the user's recent Strava activities via their stored token (legacy
`strava_connections`) and upserts them into the isolated V0 store (`v0_activities`),
de-duplicated by the Strava activity id (used as the `v0_activities` id). The Strava
sync is the SINGLE writer of `v0_activities`, so keying by the Strava id makes every
re-sync idempotent (INSERT OR IGNORE).

Lives under `runtime_v0/adapters/` (the legacy bridge): it MAY import the legacy app
(`fitmas.legacy.integrations.strava`, the ORM); the V0 core never imports it
(see tests/runtime_v0/test_import_boundaries).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Importing the orm package registers every ORM model so the mappers resolve.
from fitmas.legacy.core import orm  # noqa: F401
from fitmas.legacy.domain.execution.activities import normalize_activity_sport
from fitmas.legacy.integrations import repository as integration_repo
from fitmas.legacy.integrations import strava
from fitmas.runtime_v0.db import connect


def sync_strava_to_v0(
    *,
    legacy_db_path: Path,
    v0_db_path: Path,
    legacy_user_id: int,
    runner_user_id: int,
    per_page: int = 100,
) -> int:
    """Pull recent Strava activities and upsert into v0_activities. Returns rows inserted.

    The token lives in the legacy DB; activities are written to the isolated V0 store
    under `runner_user_id` (the V0 runner keys on the Telegram chat id). De-dup is by
    Strava activity id (the v0 row id), so re-runs only add genuinely new activities.
    """
    engine = create_engine(f"sqlite:///{legacy_db_path}")
    try:
        with Session(engine) as session:
            connection = integration_repo.get_strava_connection(session, legacy_user_id)
            if connection is None:
                return 0
            access_token = strava.refresh_token_if_needed(session, connection)
            session.commit()  # persist a refreshed token so we don't refresh every run
            raw_activities = strava.fetch_recent_activities(access_token, per_page=per_page)
    finally:
        engine.dispose()

    inserted = 0
    with connect(v0_db_path) as v0:
        for activity in raw_activities:
            strava_id = activity.get("id")
            started_at = strava._parse_strava_datetime(
                activity.get("start_date_local") or activity.get("start_date")
            )
            if strava_id is None or started_at is None:
                continue
            duration_min = int(round((activity.get("moving_time") or 0) / 60)) or None
            distance_km = (activity["distance"] / 1000.0) if activity.get("distance") is not None else None
            cursor = v0.execute(
                "insert or ignore into v0_activities "
                "(id, user_id, date, sport, duration_min, distance_km, notes, source) "
                "values (?, ?, ?, ?, ?, ?, ?, 'strava')",
                (
                    int(strava_id),
                    runner_user_id,
                    started_at.date().isoformat(),
                    normalize_activity_sport(activity.get("sport_type") or activity.get("type") or "running"),
                    duration_min,
                    distance_km,
                    activity.get("name") or "",
                ),
            )
            inserted += cursor.rowcount
        v0.commit()
    return inserted
