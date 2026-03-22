from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.time_context import DAY_KEYS, day_label_fr


def complete_session(db: Session, *, user: s.User, session_id: int) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None
    session = repo.set_scheduled_session_status(db, session.id, "done")
    _sync_current_week_day_status(db, user=user, session=session, status="done")
    return session


def skip_session(db: Session, *, user: s.User, session_id: int) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None
    session = repo.set_scheduled_session_status(db, session.id, "skipped")
    _sync_current_week_day_status(db, user=user, session=session, status="skipped")
    return session


def move_session(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    target_date: date | None = None,
) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None

    source_date = session.scheduled_date.date()
    destination_date = target_date or _find_next_open_date(db, user_id=user.id, source_date=source_date)
    if destination_date <= source_date:
        destination_date = source_date + timedelta(days=1)

    _, source_day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    destination_day_key = DAY_KEYS[destination_date.weekday()]
    destination_dt = datetime.combine(destination_date, time.min)
    destination_is_current_week = repo.get_scheduled_session_for_date(
        db,
        user.id,
        day=destination_day_key,
        scheduled_date=destination_dt,
    ) is not None

    if source_day_plan is not None and destination_is_current_week:
        plan = repo.get_active_plan(db, user.id)
        repo.move_session(db, plan.id, session.day, destination_day_key)
        source_row = repo.get_day_plan(db, plan.id, session.day)
        destination_row = repo.get_day_plan(db, plan.id, destination_day_key)
        if source_row is not None:
            repo.set_change_notes(db, source_row.id, [("Seance reportee", "Seance deplacee depuis l'app.")])
        if destination_row is not None:
            repo.set_change_notes(db, destination_row.id, [("Seance deplacee ici", "Seance replanifiee depuis l'app.")])
        repo.resync_plan_sessions(db, plan.id, timezone_name=user.timezone)
        moved = repo.get_scheduled_session_for_date(
            db,
            user.id,
            day=destination_day_key,
            scheduled_date=destination_dt,
        )
        return moved or session

    if source_day_plan is not None:
        _lighten_day_plan(db, source_day_plan)
        moved_session = s.ScheduledSession(
            user_id=user.id,
            day=destination_day_key,
            label=day_label_fr(destination_day_key, capitalize=True),
            scheduled_date=destination_dt,
            source_plan_created_at=session.source_plan_created_at,
            sport_type=session.sport_type,
            session_type=session.session_type,
            session_title=session.session_title,
            session_goal=session.session_goal,
            session_note=session.session_note,
            session_description=session.session_description,
            duration_min=session.duration_min,
            intensity=session.intensity,
            load_score=session.load_score,
            priority=session.priority,
            nutrition_focus=session.nutrition_focus,
            flexibility=session.flexibility,
            completion_status="adapted",
        )
        db.add(moved_session)

        session.sport_type = "rest"
        session.session_type = "rest"
        session.session_title = "Journee flexible"
        session.session_goal = "Recuperation et disponibilite"
        session.session_note = "Seance deplacee depuis l'app."
        session.session_description = ""
        session.duration_min = None
        session.intensity = "easy"
        session.load_score = 0
        session.priority = "Leger"
        session.nutrition_focus = "Reste simple. Le but est surtout de recuperer."
        session.flexibility = "flexible"
        session.completion_status = "adapted"
        db.commit()
        db.refresh(moved_session)
        return moved_session

    session.scheduled_date = destination_dt
    session.day = destination_day_key
    session.label = day_label_fr(destination_day_key, capitalize=True)
    session.completion_status = "adapted"
    db.commit()
    db.refresh(session)
    return session


def _find_next_open_date(db: Session, *, user_id: int, source_date: date, horizon_days: int = 14) -> date:
    sessions = repo.get_scheduled_sessions(db, user_id, limit=84)
    by_date = {session.scheduled_date.date(): session for session in sessions}
    for offset in range(1, horizon_days + 1):
        candidate = source_date + timedelta(days=offset)
        existing = by_date.get(candidate)
        if existing is None:
            return candidate
        if existing.sport_type == "rest" or existing.flexibility == "flexible":
            return candidate
    return source_date + timedelta(days=1)


def _sync_current_week_day_status(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession | None,
    status: str,
) -> None:
    if session is None:
        return
    _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    if day_plan is None:
        return
    day_plan.completion_status = status
    db.commit()


def _lighten_day_plan(db: Session, day: s.DayPlan) -> None:
    day.sport_type = "rest"
    day.session_type = "rest"
    day.session_title = "Journee flexible"
    day.session_goal = "Recuperation et disponibilite"
    day.session_note = "Seance deplacee depuis l'app. Garde de la fraicheur pour le nouveau creneau."
    day.session_description = ""
    day.duration_min = None
    day.intensity = "easy"
    day.load_score = 0
    day.priority = "Leger"
    day.nutrition_focus = "Reste simple. Le but est surtout de recuperer."
    day.flexibility = "flexible"
    day.completion_status = "adapted"
    db.commit()
    repo.set_change_notes(db, day.id, [("Seance reportee", "Deplacement confirme depuis l'app.")])
