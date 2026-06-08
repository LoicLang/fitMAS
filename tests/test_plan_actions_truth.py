from __future__ import annotations

import os
import tempfile
from fitmas.legacy.domain.planning import repository as planning_repo
from fitmas.legacy.domain.planning import template_repository as template_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-plan-actions-", suffix=".db"))

from fitmas.legacy.core import orm as s
from fitmas.legacy.domain.planning import session_actions as plan_actions
from fitmas.legacy.core.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.core.time_context import DAY_KEYS, day_label_fr, get_local_now


def _plan_day(day_key: str, *, sport_type: str = "swimming", status: str = "planned") -> dict:
    return {
        "day": day_key,
        "label": day_label_fr(day_key, capitalize=True),
        "sport_type": sport_type,
        "session_type": "technique" if sport_type != "rest" else "rest",
        "session_title": "Natation cle" if sport_type != "rest" else "Repos",
        "session_goal": "Precision" if sport_type != "rest" else "Recuperation",
        "session_note": "",
        "session_description": "Ancien contenu",
        "duration_min": 45 if sport_type != "rest" else None,
        "intensity": "moderate" if sport_type != "rest" else "easy",
        "load_score": 3 if sport_type != "rest" else 0,
        "priority": "Seance cle" if sport_type != "rest" else "Leger",
        "nutrition_focus": "",
        "flexibility": "stable",
        "completion_status": status,
    }


def setup_function() -> None:
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def test_replace_session_mutates_scheduled_session_without_touching_day_plan() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris")
        db.add(user)
        db.commit()
        db.refresh(user)
        today = get_local_now(user.timezone).date()
        today_key = DAY_KEYS[today.weekday()]
        plan = template_repo.replace_plan(
            db,
            user.id,
            intention="test",
            summary="test",
            timezone_name=user.timezone,
            days=[_plan_day(today_key)],
        )
        session = planning_repo.get_scheduled_sessions_for_date(db, user.id, target_date=today)[0]

        replaced = plan_actions.replace_session(
            db,
            user=user,
            session_id=session.id,
            new_sport_type="running",
            new_session_type="easy",
            new_title="Footing relais",
            new_duration_min=35,
            new_intensity="easy",
            rationale="Piscine fermee.",
        )

        day_plan = template_repo.get_day_plan(db, plan.id, today_key)
        assert replaced is not None
        assert replaced.sport_type == "running"
        assert replaced.session_title == "Footing relais"
        assert day_plan is not None
        assert day_plan.sport_type == "swimming"
        assert day_plan.session_title == "Natation cle"
        assert day_plan.completion_status == "planned"
    finally:
        db.close()


def test_complete_session_mutates_scheduled_session_without_touching_day_plan() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris")
        db.add(user)
        db.commit()
        db.refresh(user)
        today = get_local_now(user.timezone).date()
        today_key = DAY_KEYS[today.weekday()]
        plan = template_repo.replace_plan(
            db,
            user.id,
            intention="test",
            summary="test",
            timezone_name=user.timezone,
            days=[_plan_day(today_key)],
        )
        session = planning_repo.get_scheduled_sessions_for_date(db, user.id, target_date=today)[0]

        completed = plan_actions.complete_session(db, user=user, session_id=session.id)

        day_plan = template_repo.get_day_plan(db, plan.id, today_key)
        assert completed is not None
        assert completed.completion_status == "done"
        assert day_plan is not None
        assert day_plan.completion_status == "planned"
    finally:
        db.close()
