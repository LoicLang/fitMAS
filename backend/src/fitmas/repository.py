from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.models import (
    Activity,
    ChangeNote,
    DayId,
    DayPlan,
    Message,
    MessageRole,
    Profile,
    UserFact,
    WatchItem,
    WeeklyPlan,
)


# ── Converters ─────────────────────────────────────────────────────────────

def to_pydantic_profile(user: s.User) -> Profile:
    return Profile(
        name=user.name,
        age=user.age,
        objective=user.primary_objective or user.objective,
        coaching_style=user.coach_soul or user.coaching_style,
        primary_objective=user.primary_objective,
        weekly_structure_notes=user.weekly_structure_notes,
        coach_name=user.coach_name,
        coach_style=user.coach_style,
        coach_relationship=user.coach_relationship,
        coach_do=user.coach_do,
        coach_dont=user.coach_dont,
        coach_soul=user.coach_soul,
        onboarding_status=user.onboarding_status,
        sports=[sport.sport_type for sport in user.sports if sport.active],
        constraints=[c.text for c in user.constraints],
        preferences=[p.text for p in user.preferences],
        integrations=["Strava", "Telegram", "Manual"],
    )


def to_pydantic_day(day: s.DayPlan) -> DayPlan:
    return DayPlan(
        day=DayId(day.day),
        label=day.label,
        sport_type=day.sport_type,
        session_type=day.session_type,
        session_title=day.session_title,
        session_goal=day.session_goal,
        session_note=day.session_note,
        duration_min=day.duration_min,
        intensity=day.intensity,
        load_score=day.load_score,
        priority=day.priority,
        nutrition_focus=day.nutrition_focus,
        flexibility=day.flexibility,
        completion_status=day.completion_status,
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


def to_pydantic_fact(fact: s.UserFact) -> UserFact:
    return UserFact(
        category=fact.category,
        key=fact.key,
        value=fact.value,
        source=fact.source,
        confidence=fact.confidence,
        confirmed=fact.confirmed,
        active=fact.active,
    )


def to_pydantic_activity(activity: s.Activity) -> Activity:
    return Activity(
        id=activity.id,
        source=activity.source,
        sport_type=activity.sport_type,
        title=activity.title,
        duration_min=activity.duration_min,
        distance_m=activity.distance_m,
        elevation_m=activity.elevation_m,
        perceived_load=activity.perceived_load,
        note=activity.note,
        started_at=activity.started_at.isoformat() if activity.started_at else None,
        matched_day=activity.matched_day,
        match_reason=activity.match_reason,
    )


# ── Queries ────────────────────────────────────────────────────────────────

def get_user(db: Session) -> s.User:
    user = get_user_optional(db)
    if user is None:
        raise RuntimeError("No user in DB — onboarding required")
    return user


def get_user_optional(db: Session) -> s.User | None:
    user = db.query(s.User).first()
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


def get_active_facts(db: Session, user_id: int, limit: int = 12) -> list[s.UserFact]:
    return (
        db.query(s.UserFact)
        .filter(s.UserFact.user_id == user_id, s.UserFact.active.is_(True))
        .order_by(s.UserFact.confirmed.desc(), s.UserFact.confidence.desc(), s.UserFact.updated_at.desc())
        .limit(limit)
        .all()
    )


def get_activities(db: Session, user_id: int, limit: int = 30) -> list[s.Activity]:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id)
        .order_by(s.Activity.started_at.is_(None), s.Activity.started_at.desc(), s.Activity.created_at.desc())
        .limit(limit)
        .all()
    )


def get_activity_by_external_id(db: Session, user_id: int, external_id: str) -> s.Activity | None:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id, s.Activity.external_id == external_id)
        .first()
    )


def get_strava_connection(db: Session, user_id: int) -> s.StravaConnection | None:
    return (
        db.query(s.StravaConnection)
        .filter(s.StravaConnection.user_id == user_id)
        .first()
    )


# ── Writes ─────────────────────────────────────────────────────────────────

def add_message(db: Session, user_id: int, role: str, text: str) -> s.CoachMessage:
    msg = s.CoachMessage(user_id=user_id, role=role, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def add_activity(
    db: Session,
    *,
    user_id: int,
    source: str,
    external_id: str | None = None,
    sport_type: str,
    title: str,
    duration_min: int | None,
    distance_m: float | None,
    elevation_m: float | None,
    perceived_load: int | None,
    note: str,
    started_at,
    matched_day: str | None,
    match_reason: str,
) -> s.Activity:
    activity = s.Activity(
        user_id=user_id,
        source=source,
        external_id=external_id,
        sport_type=sport_type,
        title=title,
        duration_min=duration_min,
        distance_m=distance_m,
        elevation_m=elevation_m,
        perceived_load=perceived_load,
        note=note,
        started_at=started_at,
        matched_day=matched_day,
        match_reason=match_reason,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def replace_user_lists(
    db: Session,
    user: s.User,
    *,
    sports: list[str],
    constraints: list[str],
    preferences: list[str],
) -> None:
    db.query(s.UserSport).filter(s.UserSport.user_id == user.id).delete()
    db.query(s.UserConstraint).filter(s.UserConstraint.user_id == user.id).delete()
    db.query(s.UserPreference).filter(s.UserPreference.user_id == user.id).delete()

    for index, sport in enumerate(sports):
        db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=index))
    for text in constraints:
        db.add(s.UserConstraint(user_id=user.id, text=text))
    for text in preferences:
        db.add(s.UserPreference(user_id=user.id, text=text))

    db.commit()


def replace_user_facts(db: Session, user_id: int, facts: list[dict]) -> None:
    db.query(s.UserFact).filter(s.UserFact.user_id == user_id).delete()
    for fact in facts:
        db.add(
            s.UserFact(
                user_id=user_id,
                category=fact["category"],
                key=fact["key"],
                value=fact["value"],
                source=fact.get("source", "onboarding"),
                confidence=fact.get("confidence", 1.0),
                confirmed=fact.get("confirmed", True),
                active=fact.get("active", True),
            )
        )
    db.commit()


def upsert_facts(db: Session, user_id: int, facts: list[dict]) -> list[s.UserFact]:
    saved: list[s.UserFact] = []
    for fact in facts:
        category = fact.get("category", "").strip()
        key = fact.get("key", "").strip()
        value = fact.get("value", "").strip()
        if not category or not key:
            continue

        row = (
            db.query(s.UserFact)
            .filter(s.UserFact.user_id == user_id, s.UserFact.category == category, s.UserFact.key == key)
            .first()
        )
        action = fact.get("action", "upsert")

        if action == "archive":
            if row:
                row.active = False
                if value:
                    row.value = value
                saved.append(row)
            continue

        if not value:
            continue

        if row is None:
            row = s.UserFact(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=fact.get("source", "conversation"),
                confidence=float(fact.get("confidence", 0.7)),
                confirmed=bool(fact.get("confirmed", False)),
                active=True,
            )
            db.add(row)
        else:
            row.value = value
            row.source = fact.get("source", row.source)
            row.confidence = max(row.confidence, float(fact.get("confidence", row.confidence)))
            row.confirmed = row.confirmed or bool(fact.get("confirmed", False))
            row.active = True

        saved.append(row)

    db.commit()
    return saved


def replace_plan(
    db: Session,
    user_id: int,
    *,
    intention: str,
    summary: str,
    days: list[dict],
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

    plan = s.WeeklyPlan(
        user_id=user_id,
        intention=intention,
        summary=summary,
        status="active",
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
    return plan


def mark_day_completed(db: Session, plan_id: int, day: str) -> bool:
    """Mark a day as done when an activity matches it. Returns True if updated."""
    day_row = get_day_plan(db, plan_id, day)
    if not day_row:
        return False
    if day_row.completion_status == "done":
        return False  # already done
    day_row.completion_status = "done"
    db.commit()
    return True


def get_yesterday_status(db: Session, plan_id: int, today_key: str) -> tuple[str | None, str | None]:
    """Return (day_key, completion_status) for yesterday relative to today_key."""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    idx = day_order.index(today_key) if today_key in day_order else 0
    yesterday_key = day_order[idx - 1]  # wraps: monday → sunday
    day_row = get_day_plan(db, plan_id, yesterday_key)
    if not day_row:
        return yesterday_key, None
    return yesterday_key, day_row.completion_status


def move_session(db: Session, plan_id: int, from_day: str, to_day: str) -> None:
    """Move a session from one day to another. Source day becomes flexible/light."""
    src = get_day_plan(db, plan_id, from_day)
    dst = get_day_plan(db, plan_id, to_day)
    if not src or not dst:
        return

    # Copy session from source to destination
    dst.sport_type = src.sport_type
    dst.session_type = src.session_type
    dst.session_title = src.session_title
    dst.session_goal = src.session_goal
    dst.session_note = src.session_note
    dst.duration_min = src.duration_min
    dst.intensity = src.intensity
    dst.load_score = src.load_score
    dst.priority = src.priority
    dst.nutrition_focus = src.nutrition_focus
    dst.flexibility = "stable"
    dst.completion_status = "adapted"

    # Source becomes light
    src.sport_type = "rest"
    src.session_type = "rest"
    src.session_title = "Journee flexible"
    src.session_goal = "Creneau libere — repos ou sortie tres legere selon ressenti"
    src.session_note = "Seance deplacee. Profites-en pour recuperer ou faire un footing facile."
    src.duration_min = None
    src.intensity = "easy"
    src.load_score = 0
    src.priority = "Leger"
    src.nutrition_focus = "Reste simple. Laisse de la marge a la suite de la semaine."
    src.flexibility = "flexible"
    src.completion_status = "adapted"

    db.commit()


def set_change_notes(db: Session, day_plan_id: int, notes: list[tuple[str, str]]) -> None:
    """Replace all change notes for a day. notes = [(title, detail), ...]"""
    db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id == day_plan_id).delete()
    for title, detail in notes:
        db.add(s.ChangeNote(day_plan_id=day_plan_id, title=title, detail=detail))
    db.commit()
