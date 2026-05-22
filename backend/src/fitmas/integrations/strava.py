from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.domain.execution.activities import infer_activity_title, match_activity_to_day, normalize_activity_sport
from fitmas.domain.planning.patch_mutation_service import complete_session_from_activity_for_user, mark_session_completed_for_user
from fitmas.domain.athlete.training_load import estimate_tss

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
RECENT_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


def is_configured() -> bool:
    return bool(os.getenv("STRAVA_CLIENT_ID") and os.getenv("STRAVA_CLIENT_SECRET"))


def build_auth_url(*, callback_url: str, state: str) -> str:
    params = {
        "client_id": os.getenv("STRAVA_CLIENT_ID", ""),
        "response_type": "code",
        "redirect_uri": callback_url,
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(*, code: str) -> dict:
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": os.getenv("STRAVA_CLIENT_ID", ""),
            "client_secret": os.getenv("STRAVA_CLIENT_SECRET", ""),
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def refresh_token_if_needed(db: Session, connection: s.StravaConnection) -> str:
    now = int(datetime.now(tz=timezone.utc).timestamp())
    if connection.expires_at > now + 120:
        return connection.access_token

    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": os.getenv("STRAVA_CLIENT_ID", ""),
            "client_secret": os.getenv("STRAVA_CLIENT_SECRET", ""),
            "grant_type": "refresh_token",
            "refresh_token": connection.refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    connection.access_token = payload["access_token"]
    connection.refresh_token = payload["refresh_token"]
    connection.expires_at = payload["expires_at"]
    db.commit()
    return connection.access_token


def fetch_recent_activities(access_token: str, *, per_page: int = 20) -> list[dict]:
    response = httpx.get(
        RECENT_ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": per_page},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def store_connection_from_token_payload(db: Session, *, user_id: int, payload: dict) -> s.StravaConnection:
    connection = repo.get_strava_connection(db, user_id)
    athlete_id = int(payload["athlete"]["id"])
    scopes = ",".join(payload.get("scope", "").split(",")) if isinstance(payload.get("scope"), str) else ""

    if connection is None:
        connection = s.StravaConnection(
            user_id=user_id,
            athlete_id=athlete_id,
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            expires_at=payload["expires_at"],
            scopes=scopes,
        )
        db.add(connection)
    else:
        connection.athlete_id = athlete_id
        connection.access_token = payload["access_token"]
        connection.refresh_token = payload["refresh_token"]
        connection.expires_at = payload["expires_at"]
        connection.scopes = scopes

    db.commit()
    db.refresh(connection)
    return connection


def import_recent_activities(
    db: Session,
    *,
    user_id: int,
    connection: s.StravaConnection,
) -> int:
    access_token = refresh_token_if_needed(db, connection)
    user = repo.get_user(db)
    scheduled_sessions = repo.get_scheduled_sessions(db, user_id, limit=84)
    imported = 0
    for raw_activity in fetch_recent_activities(access_token, per_page=30):
        existing = repo.get_activity_by_external_id(db, user_id, str(raw_activity["id"]))
        if existing:
            # Backfill map data for activities imported before polyline support
            estimated_tss = estimate_tss(
                {
                    "sport_type": existing.sport_type,
                    "duration_min": existing.duration_min,
                    "perceived_load": existing.perceived_load,
                    "avg_hr": raw_activity.get("average_heartrate") or existing.avg_hr,
                },
                user,
            )
            scheduled_session = repo.find_scheduled_session_for_activity(
                db,
                user_id=user_id,
                sport_type=existing.sport_type,
                started_at=existing.started_at,
                timezone_name=user.timezone,
            )
            if not existing.map_polyline:
                polyline = (raw_activity.get("map") or {}).get("summary_polyline")
                latlng = ",".join(str(c) for c in raw_activity["start_latlng"]) if raw_activity.get("start_latlng") else None
                if polyline or latlng:
                    existing.map_polyline = polyline
                    existing.start_latlng = latlng
            if existing.tss is None and estimated_tss is not None:
                existing.tss = estimated_tss
            if existing.scheduled_session_id is None and scheduled_session is not None:
                existing.scheduled_session_id = scheduled_session.id
            if db.is_modified(existing):
                db.commit()
            if existing.scheduled_session_id is not None:
                mark_session_completed_for_user(db, user=user, session_id=existing.scheduled_session_id, source="strava")
            continue

        sport_type = normalize_activity_sport(raw_activity.get("sport_type") or raw_activity.get("type", "running"))
        duration_min = int(round(raw_activity.get("moving_time", 0) / 60)) or None
        started_at = _parse_strava_datetime(raw_activity.get("start_date_local") or raw_activity.get("start_date"))
        matched_day, match_reason = match_activity_to_day(
            sport_type=sport_type,
            started_at=started_at,
            duration_min=duration_min,
            scheduled_sessions=scheduled_sessions,
        )
        estimated_tss = estimate_tss(
            {
                "sport_type": sport_type,
                "duration_min": duration_min,
                "perceived_load": None,
                "avg_hr": raw_activity.get("average_heartrate"),
            },
            user,
        )
        scheduled_session = repo.find_scheduled_session_for_activity(
            db,
            user_id=user_id,
            sport_type=sport_type,
            started_at=started_at,
            timezone_name=user.timezone,
        )

        activity = repo.add_activity(
            db,
            user_id=user_id,
            source="strava",
            scheduled_session_id=scheduled_session.id if scheduled_session else None,
            sport_type=sport_type,
            title=raw_activity.get("name") or infer_activity_title(sport_type, duration_min, ""),
            duration_min=duration_min,
            distance_m=raw_activity.get("distance"),
            elevation_m=raw_activity.get("total_elevation_gain"),
            perceived_load=None,
            note="",
            started_at=started_at,
            matched_day=matched_day,
            match_reason=match_reason,
            external_id=str(raw_activity["id"]),
            avg_hr=raw_activity.get("average_heartrate"),
            max_hr=raw_activity.get("max_heartrate"),
            avg_speed=raw_activity.get("average_speed"),
            calories=raw_activity.get("calories") or raw_activity.get("kilojoules"),
            suffer_score=raw_activity.get("suffer_score"),
            tss=estimated_tss,
            map_polyline=(raw_activity.get("map") or {}).get("summary_polyline"),
            start_latlng=",".join(str(c) for c in raw_activity["start_latlng"]) if raw_activity.get("start_latlng") else None,
        )

        if activity.scheduled_session_id is not None:
            complete_session_from_activity_for_user(
                db,
                user=user,
                session_id=activity.scheduled_session_id,
                plan_id=None,
                matched_day=matched_day if match_reason != "activite hors semaine courante" else None,
                source="strava",
            )

        imported += 1

        # Adaptive plan: estimate thresholds + check if activity triggers adaptation
        try:
            from fitmas.domain.athlete.threshold_estimation import update_threshold_facts
            update_threshold_facts(db, user, activity)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Threshold estimation failed (non-blocking)")
        try:
            from fitmas.domain.planning.adaptation import check_and_adapt_post_activity
            check_and_adapt_post_activity(db, user, activity)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Adaptation post_activity check failed (non-blocking)")

    connection.last_sync_at = datetime.now(tz=timezone.utc)
    db.commit()
    return imported


def _parse_strava_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
