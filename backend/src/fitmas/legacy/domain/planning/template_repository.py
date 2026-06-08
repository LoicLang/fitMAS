from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.core.time_context import DAY_KEYS, current_week_dates, get_local_now
from fitmas.legacy.domain.planning import repository as planning_repo
from fitmas.legacy.domain.planning.models import compute_load_band
from fitmas.legacy.domain.planning.periodization import build_week_label, compute_mesocycle_state, derive_total_weeks
from fitmas.legacy.domain.planning.view_models import ChangeNote, DayId, DayPlan, WatchItem, WeeklyPlan


def to_pydantic_day(day: s.DayPlan) -> DayPlan:
    load_band = compute_load_band(
        sport_type=day.sport_type,
        session_type=day.session_type,
        intensity=day.intensity,
        load_score=day.load_score,
    )
    return DayPlan(
        day=DayId(day.day),
        label=day.label,
        sport_type=day.sport_type,
        session_type=day.session_type,
        session_title=day.session_title,
        session_goal=day.session_goal,
        session_note=day.session_note,
        session_description=day.session_description or "",
        duration_min=day.duration_min,
        intensity=day.intensity,
        load_score=day.load_score,
        load_band=load_band,
        priority=day.priority,
        nutrition_focus=day.nutrition_focus,
        flexibility=day.flexibility,
        completion_status=day.completion_status,
        change_notes=[ChangeNote(title=n.title, detail=n.detail) for n in day.change_notes],
        watch_items=[WatchItem(title=w.title, detail=w.detail) for w in day.watch_items],
    )


def to_pydantic_plan(plan: s.WeeklyPlan) -> WeeklyPlan:
    total_weeks = int(getattr(plan, "total_weeks", 0) or 0)
    if total_weeks < 1:
        total_weeks = derive_total_weeks(
            mesocycle_number=getattr(plan, "mesocycle_number", 1),
            mesocycle_week=getattr(plan, "mesocycle_week", 1),
        )
    mesocycle = compute_mesocycle_state(total_weeks=total_weeks)
    return WeeklyPlan(
        intention=plan.intention,
        summary=plan.summary,
        mesocycle_week=mesocycle.week_in_cycle,
        mesocycle_number=mesocycle.cycle_number,
        cycle_length=mesocycle.cycle_length,
        total_weeks=mesocycle.total_weeks,
        is_deload=mesocycle.is_recovery_week,
        week_label=build_week_label(mesocycle),
        days=[to_pydantic_day(d) for d in plan.days],
    )


def get_active_plan_optional(db: Session, user_id: int) -> s.WeeklyPlan | None:
    return (
        db.query(s.WeeklyPlan)
        .filter(s.WeeklyPlan.user_id == user_id, s.WeeklyPlan.status == "active")
        .first()
    )


def get_active_plan(db: Session, user_id: int) -> s.WeeklyPlan:
    plan = get_active_plan_optional(db, user_id)
    if plan is None:
        raise RuntimeError("No active plan in DB")
    return plan


def get_plan_optional(db: Session, plan_id: int) -> s.WeeklyPlan | None:
    return db.query(s.WeeklyPlan).filter(s.WeeklyPlan.id == plan_id).first()


def get_day_plan(db: Session, plan_id: int, day: str) -> s.DayPlan | None:
    return (
        db.query(s.DayPlan)
        .filter(s.DayPlan.weekly_plan_id == plan_id, s.DayPlan.day == day)
        .first()
    )


def replace_plan(
    db: Session,
    user_id: int,
    *,
    intention: str,
    summary: str,
    days: list[dict],
    timezone_name: str | None = None,
    now: datetime | None = None,
    mesocycle_week: int = 1,
    mesocycle_number: int = 1,
    total_weeks: int = 1,
) -> s.WeeklyPlan:
    plans = db.query(s.WeeklyPlan).filter(s.WeeklyPlan.user_id == user_id).all()
    plan_ids = [plan.id for plan in plans]
    if plan_ids:
        day_ids = [
            row[0]
            for row in db.query(s.DayPlan.id).filter(s.DayPlan.weekly_plan_id.in_(plan_ids)).all()
        ]
        if day_ids:
            db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id.in_(day_ids)).delete(synchronize_session=False)
            db.query(s.WatchItem).filter(s.WatchItem.day_plan_id.in_(day_ids)).delete(synchronize_session=False)
            db.query(s.DayPlan).filter(s.DayPlan.id.in_(day_ids)).delete(synchronize_session=False)
        db.query(s.WeeklyPlan).filter(s.WeeklyPlan.id.in_(plan_ids)).delete(synchronize_session=False)
    db.commit()
    for stale_plan in plans:
        if db.object_session(stale_plan) is db:
            db.expunge(stale_plan)

    plan = s.WeeklyPlan(
        user_id=user_id,
        intention=intention,
        summary=summary,
        status="active",
        mesocycle_week=mesocycle_week,
        mesocycle_number=mesocycle_number,
        total_weeks=max(1, int(total_weeks or 1)),
    )
    db.add(plan)
    db.flush()

    for sort_order, day in enumerate(days):
        change_notes = day.pop("change_notes", [])
        watch_items = day.pop("watch_items", [])
        day_row = s.DayPlan(weekly_plan_id=plan.id, sort_order=sort_order, **day)
        db.add(day_row)
        db.flush()
        for title, detail in change_notes:
            db.add(s.ChangeNote(day_plan_id=day_row.id, title=title, detail=detail))
        for title, detail in watch_items:
            db.add(s.WatchItem(day_plan_id=day_row.id, title=title, detail=detail))

    db.commit()
    db.refresh(plan)
    sync_scheduled_sessions_for_plan(db, user_id=user_id, plan=plan, timezone_name=timezone_name, now=now)
    return plan


def sync_scheduled_sessions_for_plan(
    db: Session,
    *,
    user_id: int,
    plan: s.WeeklyPlan,
    timezone_name: str | None,
    now: datetime | None = None,
) -> None:
    local_now = get_local_now(timezone_name, now=now)
    current_date = local_now.date()
    current_day_index = local_now.weekday()

    for day_row in plan.days:
        target_day_index = DAY_KEYS.index(day_row.day)
        scheduled_date = current_date + timedelta(days=target_day_index - current_day_index)
        if scheduled_date < current_date:
            continue

        scheduled_dt = datetime.combine(scheduled_date, datetime.min.time())
        session = planning_repo.get_scheduled_session_for_date(
            db,
            user_id,
            day=day_row.day,
            scheduled_date=scheduled_dt,
        )
        if session is None:
            session = s.ScheduledSession(
                user_id=user_id,
                day=day_row.day,
                label=day_row.label,
                scheduled_date=scheduled_dt,
                source_plan_created_at=plan.created_at,
            )
            db.add(session)

        session.label = day_row.label
        session.source_plan_created_at = plan.created_at
        session.sport_type = day_row.sport_type
        session.session_type = day_row.session_type
        session.session_title = day_row.session_title
        session.session_goal = day_row.session_goal
        session.session_note = day_row.session_note
        session.session_description = day_row.session_description
        session.duration_min = day_row.duration_min
        session.intensity = day_row.intensity
        session.load_score = day_row.load_score
        session.priority = day_row.priority
        session.nutrition_focus = day_row.nutrition_focus
        session.flexibility = day_row.flexibility
        if session.completion_status != "done":
            session.completion_status = day_row.completion_status

    db.commit()


def mark_day_completed(db: Session, plan_id: int, day: str) -> bool:
    day_row = get_day_plan(db, plan_id, day)
    if not day_row:
        return False
    if day_row.completion_status == "done":
        return False
    day_row.completion_status = "done"
    db.commit()
    return True


def get_current_week_day_plan_for_session(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> tuple[s.WeeklyPlan | None, s.DayPlan | None]:
    week_dates = current_week_dates(user.timezone)
    if week_dates.get(session.day) != session.scheduled_date.date():
        return None, None
    plan = get_active_plan(db, user.id)
    return plan, get_day_plan(db, plan.id, session.day)


def resync_plan_sessions(db: Session, plan_id: int, *, timezone_name: str | None) -> bool:
    plan = get_plan_optional(db, plan_id)
    if plan is None:
        return False
    sync_scheduled_sessions_for_plan(db, user_id=plan.user_id, plan=plan, timezone_name=timezone_name)
    return True


def get_yesterday_status(db: Session, plan_id: int, today_key: str) -> tuple[str | None, str | None]:
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    idx = day_order.index(today_key) if today_key in day_order else 0
    yesterday_key = day_order[idx - 1]
    day_row = get_day_plan(db, plan_id, yesterday_key)
    if not day_row:
        return yesterday_key, None
    return yesterday_key, day_row.completion_status


def move_session(db: Session, plan_id: int, from_day: str, to_day: str) -> None:
    src = get_day_plan(db, plan_id, from_day)
    dst = get_day_plan(db, plan_id, to_day)
    if not src or not dst:
        return

    dst.sport_type = src.sport_type
    dst.session_type = src.session_type
    dst.session_title = src.session_title
    dst.session_goal = src.session_goal
    dst.session_note = src.session_note
    dst.session_description = src.session_description
    dst.duration_min = src.duration_min
    dst.intensity = src.intensity
    dst.load_score = src.load_score
    dst.priority = src.priority
    dst.nutrition_focus = src.nutrition_focus
    dst.flexibility = "stable"
    dst.completion_status = "adapted"

    src.sport_type = "rest"
    src.session_type = "rest"
    src.session_title = "Journee flexible"
    src.session_goal = "Creneau libere - repos ou sortie tres legere selon ressenti"
    src.session_note = "Seance deplacee. Profites-en pour recuperer ou faire un footing facile."
    src.session_description = ""
    src.duration_min = None
    src.intensity = "easy"
    src.load_score = 0
    src.priority = "Leger"
    src.nutrition_focus = "Reste simple. Laisse de la marge a la suite de la semaine."
    src.flexibility = "flexible"
    src.completion_status = "adapted"

    db.commit()


def set_change_notes(db: Session, day_plan_id: int, notes: list[tuple[str, str]]) -> None:
    db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id == day_plan_id).delete()
    for title, detail in notes:
        db.add(s.ChangeNote(day_plan_id=day_plan_id, title=title, detail=detail))
    db.commit()
