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
    _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    if day_plan is not None:
        _apply_light_day_fields(day_plan, rationale=rationale)
        repo.set_change_notes(db, day_plan.id, [("Journee allegee", rationale or "Journee allegee.")])

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

    _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    if day_plan is not None:
        if new_title:
            day_plan.session_title = new_title
        if new_goal:
            day_plan.session_goal = new_goal
        if rationale:
            day_plan.session_note = rationale
        repo.set_change_notes(db, day_plan.id, [("Seance modifiee", rationale or "Seance ajustee.")])

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

    _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    if day_plan is not None:
        _apply_replacement_fields(
            day_plan,
            new_sport_type=new_sport_type,
            new_session_type=new_session_type,
            new_duration_min=new_duration_min,
            new_intensity=new_intensity,
            new_description=new_description,
            new_title=new_title,
            new_goal=new_goal,
            rationale=rationale,
        )
        repo.set_change_notes(db, day_plan.id, [("Seance remplacee", rationale or "Seance adaptee.")])

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

    first_plan, first_day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=first)
    _, second_day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=second)
    if first_day_plan is not None and second_day_plan is not None and first_plan is not None:
        _swap_day_plan_content(first_day_plan, second_day_plan)
        db.commit()
        repo.set_change_notes(db, first_day_plan.id, [("Seance echangee", rationale or "Seances echangees.")])
        repo.set_change_notes(db, second_day_plan.id, [("Seance echangee", rationale or "Seances echangees.")])
        repo.resync_plan_sessions(db, first_plan.id, timezone_name=user.timezone)
        refreshed_first = repo.get_scheduled_session(db, user.id, first.id) or first
        refreshed_second = repo.get_scheduled_session(db, user.id, second.id) or second
        return refreshed_first, refreshed_second

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
    _apply_light_day_fields(day, rationale="Seance deplacee depuis l'app. Garde de la fraicheur pour le nouveau creneau.")
    db.commit()
    repo.set_change_notes(db, day.id, [("Seance reportee", "Deplacement confirme depuis l'app.")])


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


def _swap_day_plan_content(first: s.DayPlan, second: s.DayPlan) -> None:
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


def _estimate_load_score(intensity: str | None, duration_min: int | None) -> int:
    """Rough load score: points per 30min based on intensity."""
    if not duration_min or duration_min <= 0:
        return 0
    per_30 = {"easy": 1, "moderate": 2, "hard": 3}
    base = per_30.get(intensity or "moderate", 2)
    return max(1, round(base * duration_min / 30))


def _apply_replacement_fields(
    target,  # ScheduledSession or DayPlan
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
    if new_sport_type is not None:
        target.sport_type = new_sport_type
    if new_session_type is not None:
        target.session_type = new_session_type
    if new_duration_min is not None:
        target.duration_min = new_duration_min
    if new_intensity is not None:
        target.intensity = new_intensity
    if new_description is not None:
        desc_attr = "session_description" if hasattr(target, "session_description") else "session_description"
        setattr(target, desc_attr, new_description)
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


def _apply_light_day_fields(day: s.DayPlan, *, rationale: str | None) -> None:
    day.sport_type = "rest"
    day.session_type = "rest"
    day.session_title = "Journee flexible"
    day.session_goal = "Recuperation et disponibilite"
    day.session_note = rationale or "Journee allegee."
    day.session_description = ""
    day.duration_min = None
    day.intensity = "easy"
    day.load_score = 0
    day.priority = "Leger"
    day.nutrition_focus = "Reste simple. Le but est surtout de recuperer."
    day.flexibility = "flexible"
    day.completion_status = "adapted"
