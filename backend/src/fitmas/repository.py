from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.models import (
    ChangeNote,
    DayId,
    DayPlan,
    Message,
    MessageRole,
    Profile,
    WatchItem,
    WeeklyPlan,
)


# ── Converters ─────────────────────────────────────────────────────────────

def to_pydantic_profile(user: s.User) -> Profile:
    return Profile(
        name=user.name,
        age=user.age,
        objective=user.objective,
        coaching_style=user.coaching_style,
        constraints=[c.text for c in user.constraints],
        preferences=[p.text for p in user.preferences],
        integrations=["Apple Health", "Strava", "Telegram"],
    )


def to_pydantic_day(day: s.DayPlan) -> DayPlan:
    return DayPlan(
        day=DayId(day.day),
        label=day.label,
        session_title=day.session_title,
        session_goal=day.session_goal,
        session_note=day.session_note,
        priority=day.priority,
        nutrition_focus=day.nutrition_focus,
        flexibility=day.flexibility,
        change_notes=[ChangeNote(title=n.title, detail=n.detail) for n in day.change_notes],
        watch_items=[WatchItem(title=w.title, detail=w.detail) for w in day.watch_items],
    )


def to_pydantic_plan(plan: s.WeeklyPlan) -> WeeklyPlan:
    return WeeklyPlan(
        intention=plan.intention,
        summary=plan.summary,
        days=[to_pydantic_day(d) for d in plan.days],
    )


def to_pydantic_message(msg: s.CoachMessage) -> Message:
    return Message(role=MessageRole(msg.role), text=msg.text)


# ── Queries ────────────────────────────────────────────────────────────────

def get_user(db: Session) -> s.User:
    user = db.query(s.User).first()
    if user is None:
        raise RuntimeError("No user in DB — did seed run?")
    return user


def get_active_plan(db: Session, user_id: int) -> s.WeeklyPlan:
    plan = (
        db.query(s.WeeklyPlan)
        .filter(s.WeeklyPlan.user_id == user_id, s.WeeklyPlan.status == "active")
        .first()
    )
    if plan is None:
        raise RuntimeError("No active plan in DB")
    return plan


def get_day_plan(db: Session, plan_id: int, day: str) -> s.DayPlan | None:
    return (
        db.query(s.DayPlan)
        .filter(s.DayPlan.weekly_plan_id == plan_id, s.DayPlan.day == day)
        .first()
    )


def get_messages(db: Session, user_id: int) -> list[s.CoachMessage]:
    return (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user_id)
        .order_by(s.CoachMessage.id)
        .all()
    )


# ── Writes ─────────────────────────────────────────────────────────────────

def add_message(db: Session, user_id: int, role: str, text: str) -> s.CoachMessage:
    msg = s.CoachMessage(user_id=user_id, role=role, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def move_session(db: Session, plan_id: int, from_day: str, to_day: str) -> None:
    """Move a session from one day to another. Source day becomes flexible/light."""
    src = get_day_plan(db, plan_id, from_day)
    dst = get_day_plan(db, plan_id, to_day)
    if not src or not dst:
        return

    # Copy session from source to destination
    dst.session_title = src.session_title
    dst.session_goal = src.session_goal
    dst.session_note = src.session_note
    dst.priority = src.priority
    dst.flexibility = "stable"

    # Source becomes light
    src.session_title = "Journee flexible"
    src.session_goal = "Creneau libere — repos ou sortie tres legere selon ressenti"
    src.session_note = "Seance deplacee. Profites-en pour recuperer ou faire un footing facile."
    src.priority = "Leger"
    src.flexibility = "flexible"

    db.commit()


def set_change_notes(db: Session, day_plan_id: int, notes: list[tuple[str, str]]) -> None:
    """Replace all change notes for a day. notes = [(title, detail), ...]"""
    db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id == day_plan_id).delete()
    for title, detail in notes:
        db.add(s.ChangeNote(day_plan_id=day_plan_id, title=title, detail=detail))
    db.commit()
