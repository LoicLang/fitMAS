from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.core.time_context import DAY_KEYS, day_label_fr
from fitmas.domain.planning import repository as repo


def create_session(
    db: Session,
    *,
    user: s.User,
    target_date: date,
    sport_type: str,
    session_type: str = "easy",
    title: str,
    goal: str = "",
    duration_min: int | None = None,
    intensity: str = "easy",
    description: str = "",
    rationale: str | None = None,
    source_plan_created_at: datetime | None = None,
) -> s.ScheduledSession:
    day_key = DAY_KEYS[target_date.weekday()]
    session = s.ScheduledSession(
        user_id=user.id,
        day=day_key,
        label=day_label_fr(day_key, capitalize=True),
        scheduled_date=datetime.combine(target_date, time.min),
        source_plan_created_at=source_plan_created_at,
        sport_type=sport_type,
        session_type=session_type or "easy",
        session_title=title,
        session_goal=goal or title,
        session_note=rationale or "",
        session_description=description or "",
        duration_min=duration_min,
        intensity=intensity or "easy",
        load_score=_load_score_for_intensity(intensity),
        priority="Normal",
        nutrition_focus="",
        flexibility="stable",
        completion_status="planned",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def complete_session(db: Session, *, user: s.User, session_id: int) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None
    return repo.set_scheduled_session_status(db, session.id, "done")


def skip_session(db: Session, *, user: s.User, session_id: int) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None
    return repo.set_scheduled_session_status(db, session.id, "skipped")


def lighten_session(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    rationale: str | None = None,
) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None

    _apply_light_session_fields(session, rationale=rationale)
    db.commit()
    db.refresh(session)
    return session


def update_session_details(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    new_title: str | None = None,
    new_goal: str | None = None,
    rationale: str | None = None,
) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None

    if new_title:
        session.session_title = new_title
    if new_goal:
        session.session_goal = new_goal
    if rationale:
        session.session_note = rationale

    db.commit()
    db.refresh(session)
    return session


def replace_session(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    new_sport_type: str | None = None,
    new_session_type: str | None = None,
    new_duration_min: int | None = None,
    new_intensity: str | None = None,
    new_description: str | None = None,
    new_title: str | None = None,
    new_goal: str | None = None,
    rationale: str | None = None,
) -> s.ScheduledSession | None:
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        return None

    _apply_replacement_fields(
        session,
        new_sport_type=new_sport_type,
        new_session_type=new_session_type,
        new_duration_min=new_duration_min,
        new_intensity=new_intensity,
        new_description=new_description,
        new_title=new_title,
        new_goal=new_goal,
        rationale=rationale,
    )

    db.commit()
    db.refresh(session)
    return session


def swap_sessions(
    db: Session,
    *,
    user: s.User,
    first_session_id: int,
    second_session_id: int,
    rationale: str | None = None,
) -> tuple[s.ScheduledSession, s.ScheduledSession] | None:
    first = repo.get_scheduled_session(db, user.id, first_session_id)
    second = repo.get_scheduled_session(db, user.id, second_session_id)
    if first is None or second is None or first.id == second.id:
        return None

    _swap_session_content(first, second)
    if rationale:
        first.session_note = rationale
        second.session_note = rationale
    db.commit()
    db.refresh(first)
    db.refresh(second)
    return first, second


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
    if target_date is None and destination_date <= source_date:
        destination_date = source_date + timedelta(days=1)

    target_slot = _scheduled_session_on_date(db, user_id=user.id, target_date=destination_date, exclude_session_id=session.id)
    if target_slot is not None:
        _assign_session_date(target_slot, source_date)
        target_slot.completion_status = "adapted"
    else:
        db.add(_build_source_placeholder(user=user, source=session, source_date=source_date))
    _assign_session_date(session, destination_date)
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


def _scheduled_session_on_date(
    db: Session,
    *,
    user_id: int,
    target_date: date,
    exclude_session_id: int | None = None,
) -> s.ScheduledSession | None:
    sessions = repo.get_scheduled_sessions_for_date(db, user_id, target_date=target_date)
    for candidate in sessions:
        if exclude_session_id is not None and candidate.id == exclude_session_id:
            continue
        return candidate
    return None


def _assign_session_date(session: s.ScheduledSession, target_date: date) -> None:
    day_key = DAY_KEYS[target_date.weekday()]
    session.scheduled_date = datetime.combine(target_date, time.min)
    session.day = day_key
    session.label = day_label_fr(day_key, capitalize=True)


def _build_source_placeholder(
    *,
    user: s.User,
    source: s.ScheduledSession,
    source_date: date,
) -> s.ScheduledSession:
    day_key = DAY_KEYS[source_date.weekday()]
    return s.ScheduledSession(
        user_id=user.id,
        day=day_key,
        label=day_label_fr(day_key, capitalize=True),
        scheduled_date=datetime.combine(source_date, time.min),
        source_plan_created_at=source.source_plan_created_at,
        sport_type="rest",
        session_type="rest",
        session_title="Journee flexible",
        session_goal="Recuperation et disponibilite",
        session_note="Seance deplacee depuis l'app.",
        session_description="",
        duration_min=None,
        intensity="easy",
        load_score=0,
        priority="Leger",
        nutrition_focus="Reste simple. Le but est surtout de recuperer.",
        flexibility="flexible",
        completion_status="adapted",
    )


def _swap_session_content(first: s.ScheduledSession, second: s.ScheduledSession) -> None:
    fields = (
        "sport_type",
        "session_type",
        "session_title",
        "session_goal",
        "session_note",
        "session_description",
        "duration_min",
        "intensity",
        "load_score",
        "priority",
        "nutrition_focus",
        "flexibility",
        "completion_status",
    )
    for field in fields:
        first_value = getattr(first, field)
        second_value = getattr(second, field)
        setattr(first, field, second_value)
        setattr(second, field, first_value)


def _apply_light_session_fields(session: s.ScheduledSession, *, rationale: str | None) -> None:
    session.sport_type = "rest"
    session.session_type = "rest"
    session.session_title = "Journee flexible"
    session.session_goal = "Recuperation et disponibilite"
    session.session_note = rationale or "Journee allegee."
    session.session_description = ""
    session.duration_min = None
    session.intensity = "easy"
    session.load_score = 0
    session.priority = "Leger"
    session.nutrition_focus = "Reste simple. Le but est surtout de recuperer."
    session.flexibility = "flexible"
    session.completion_status = "adapted"


def _load_score_for_intensity(intensity: str | None) -> int:
    value = str(intensity or "").strip().lower()
    if value == "hard":
        return 4
    if value == "moderate":
        return 3
    return 1


def _estimate_load_score(intensity: str | None, duration_min: int | None) -> int:
    """Rough load score: points per 30min based on intensity."""
    if not duration_min or duration_min <= 0:
        return 0
    per_30 = {"easy": 1, "moderate": 2, "hard": 3}
    base = per_30.get(intensity or "moderate", 2)
    return max(1, round(base * duration_min / 30))


def _apply_replacement_fields(
    target: s.ScheduledSession,
    *,
    new_sport_type: str | None,
    new_session_type: str | None,
    new_duration_min: int | None,
    new_intensity: str | None,
    new_description: str | None,
    new_title: str | None,
    new_goal: str | None,
    rationale: str | None,
) -> None:
    sport_changed = bool(new_sport_type and new_sport_type != getattr(target, "sport_type", None))
    type_changed = bool(new_session_type and new_session_type != getattr(target, "session_type", None))
    if new_sport_type is not None:
        target.sport_type = new_sport_type
    if new_session_type is not None:
        target.session_type = new_session_type
    if new_duration_min is not None:
        target.duration_min = new_duration_min
    if new_intensity is not None:
        target.intensity = new_intensity
    if new_description is not None:
        target.session_description = new_description
    elif sport_changed or type_changed:
        target.session_description = ""
    if new_title is not None:
        target.session_title = new_title
    if new_goal is not None:
        target.session_goal = new_goal
    if rationale is not None:
        target.session_note = rationale

    # Recalculate load_score if intensity or duration changed
    if new_intensity is not None or new_duration_min is not None:
        eff_intensity = new_intensity or getattr(target, "intensity", "moderate")
        eff_duration = new_duration_min or getattr(target, "duration_min", None)
        target.load_score = _estimate_load_score(eff_intensity, eff_duration)

    target.completion_status = "adapted"
