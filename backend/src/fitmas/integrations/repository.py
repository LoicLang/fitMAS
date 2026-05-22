from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from fitmas import schema as s


def get_strava_connection(db: Session, user_id: int) -> s.StravaConnection | None:
    return (
        db.query(s.StravaConnection)
        .filter(s.StravaConnection.user_id == user_id)
        .order_by(s.StravaConnection.id.desc())
        .first()
    )


def upsert_strava_connection(
    db: Session,
    *,
    user_id: int,
    athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    scopes: str,
) -> s.StravaConnection:
    connection = get_strava_connection(db, user_id)
    if connection is None:
        connection = s.StravaConnection(user_id=user_id, athlete_id=athlete_id)
        db.add(connection)

    connection.athlete_id = athlete_id
    connection.access_token = access_token
    connection.refresh_token = refresh_token
    connection.expires_at = expires_at
    connection.scopes = scopes
    db.commit()
    db.refresh(connection)
    return connection


def update_strava_tokens(
    db: Session,
    connection: s.StravaConnection,
    *,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> s.StravaConnection:
    connection.access_token = access_token
    connection.refresh_token = refresh_token
    connection.expires_at = expires_at
    db.commit()
    db.refresh(connection)
    return connection


def mark_strava_synced(
    db: Session,
    connection: s.StravaConnection,
    *,
    synced_at: datetime,
) -> s.StravaConnection:
    connection.last_sync_at = synced_at
    db.commit()
    db.refresh(connection)
    return connection
