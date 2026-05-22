from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.core.time_context import get_local_now


def get_scheduled_sessions(
    db: Session,
    user_id: int,
    *,
    date_from: date | None = None,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    query = db.query(s.ScheduledSession).filter(s.ScheduledSession.user_id == user_id)
    if date_from is not None:
        return (
            query
            .filter(s.ScheduledSession.scheduled_date >= datetime.combine(date_from, time.min))
            .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
            .limit(limit)
            .all()
        )
    sessions = (
        query
        .order_by(s.ScheduledSession.scheduled_date.desc(), s.ScheduledSession.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(sessions))


def get_scheduled_sessions_for_date(
    db: Session,
    user_id: int,
    *,
    target_date: date,
) -> list[s.ScheduledSession]:
    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
        .all()
    )


def get_scheduled_sessions_between_dates(
    db: Session,
    user_id: int,
    *,
    start_date: date,
    end_date: date,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date + timedelta(days=1), time.min)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
        .limit(limit)
        .all()
    )


def get_scheduled_session_for_date(
    db: Session,
    user_id: int,
    *,
    day: str,
    scheduled_date: datetime,
) -> s.ScheduledSession | None:
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.day == day,
            s.ScheduledSession.scheduled_date == scheduled_date,
        )
        .first()
    )


def get_scheduled_session(db: Session, user_id: int, session_id: int) -> s.ScheduledSession | None:
    return (
        db.query(s.ScheduledSession)
        .filter(s.ScheduledSession.user_id == user_id, s.ScheduledSession.id == session_id)
        .first()
    )


def get_today_scheduled_session(
    db: Session,
    user_id: int,
    *,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    local_date = get_local_now(timezone_name).date()
    day_start = datetime.combine(local_date, time.min)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.id.asc())
        .first()
    )


def find_scheduled_session_for_activity(
    db: Session,
    *,
    user_id: int,
    sport_type: str,
    started_at: datetime | None,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    if started_at is None:
        local_date = get_local_now(timezone_name).date()
    elif started_at.tzinfo is None:
        local_date = started_at.date()
    else:
        local_date = get_local_now(timezone_name, now=started_at).date()

    day_start = datetime.combine(local_date, time.min)
    day_end = day_start + timedelta(days=1)
    sessions = (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.id.asc())
        .all()
    )
    if not sessions:
        return None

    for session in sessions:
        if session.sport_type == sport_type and session.completion_status != "done":
            return session
    return None


def add_plan_mutation_event(
    db: Session,
    *,
    user_id: int,
    source: str,
    trigger_type: str,
    command_type: str,
    target_session_ids: list[int],
    before_snapshot: dict | None = None,
    after_snapshot: dict | None = None,
    reason: dict | None = None,
    impact: dict | None = None,
    user_visible_summary: str = "",
    explained_to_user: bool = False,
    conversation_turn_id: int | None = None,
) -> s.PlanMutationEventRecord:
    row = s.PlanMutationEventRecord(
        user_id=user_id,
        source=source,
        trigger_type=trigger_type,
        command_type=command_type,
        target_session_ids_json=_json_dumps(target_session_ids),
        before_snapshot_json=_json_dumps(before_snapshot or {}),
        after_snapshot_json=_json_dumps(after_snapshot or {}),
        reason_json=_json_dumps(reason or {}),
        impact_json=_json_dumps(impact or {}),
        user_visible_summary=user_visible_summary,
        explained_to_user=explained_to_user,
        conversation_turn_id=conversation_turn_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_scheduled_session_completed(db: Session, session_id: int | None) -> bool:
    if session_id is None:
        return False
    session = db.query(s.ScheduledSession).filter(s.ScheduledSession.id == session_id).first()
    if not session or session.completion_status == "done":
        return False
    session.completion_status = "done"
    db.commit()
    return True


def set_scheduled_session_status(db: Session, session_id: int, status: str) -> s.ScheduledSession | None:
    session = db.query(s.ScheduledSession).filter(s.ScheduledSession.id == session_id).first()
    if session is None:
        return None
    session.completion_status = status
    db.commit()
    db.refresh(session)
    return session


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
