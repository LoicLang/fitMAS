from __future__ import annotations

import os
import tempfile
from datetime import datetime

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-phase5-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.decision_contracts import MutationDecision
from fitmas.plan_mutation_service import apply_decisions_for_user


def setup_function() -> None:
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def test_same_sport_proximity_guard_blocks_apply_and_event() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris")
        db.add(user)
        db.commit()
        db.refresh(user)
        repo.replace_plan(
            db,
            user.id,
            intention="template actif",
            summary="support test",
            timezone_name=user.timezone,
            days=[
                {
                    "day": "monday",
                    "label": "Lundi",
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Repos",
                    "session_goal": "Recuperer",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": None,
                    "intensity": "easy",
                    "load_score": 0,
                    "priority": "Leger",
                    "nutrition_focus": "",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                }
            ],
        )
        target = s.ScheduledSession(
            user_id=user.id,
            day="monday",
            label="Lundi",
            scheduled_date=datetime.fromisoformat("2026-04-13T07:00:00"),
            sport_type="running",
            session_type="tempo",
            session_title="Tempo 1",
            session_goal="Stimulus",
            session_note="",
            session_description="",
            duration_min=45,
            intensity="moderate",
            load_score=3,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        neighbor = s.ScheduledSession(
            user_id=user.id,
            day="thursday",
            label="Jeudi",
            scheduled_date=datetime.fromisoformat("2026-04-16T07:00:00"),
            sport_type="running",
            session_type="tempo",
            session_title="Tempo 2",
            session_goal="Stimulus",
            session_note="",
            session_description="",
            duration_min=45,
            intensity="moderate",
            load_score=3,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        db.add_all([target, neighbor])
        db.commit()
        db.refresh(target)

        result = apply_decisions_for_user(
            db,
            user=user,
            decisions=[
                MutationDecision(
                    mutation_type="move_session",
                    target_session_id=target.id,
                    target_date="2026-04-15",
                    rationale="indispo",
                    fitmas_message="Je deplace.",
                )
            ],
        )

        db.refresh(target)
        events = db.query(s.PlanMutationEventRecord).all()

        assert result is not None
        assert result.applied_count == 0
        assert result.event_count == 0
        assert target.scheduled_date.date().isoformat() == "2026-04-13"
        assert events == []
    finally:
        db.close()


def test_move_to_stable_recovery_applies_and_moves_recovery() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris")
        db.add(user)
        db.commit()
        db.refresh(user)
        repo.replace_plan(
            db,
            user.id,
            intention="template actif",
            summary="support test",
            timezone_name=user.timezone,
            days=[
                {
                    "day": "monday",
                    "label": "Lundi",
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Repos",
                    "session_goal": "Recuperer",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": None,
                    "intensity": "easy",
                    "load_score": 0,
                    "priority": "Leger",
                    "nutrition_focus": "",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                }
            ],
        )
        target = s.ScheduledSession(
            user_id=user.id,
            day="monday",
            label="Lundi",
            scheduled_date=datetime.fromisoformat("2026-04-13T07:00:00"),
            sport_type="running",
            session_type="tempo",
            session_title="Tempo",
            session_goal="Stimulus",
            session_note="",
            session_description="",
            duration_min=45,
            intensity="moderate",
            load_score=3,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        recovery = s.ScheduledSession(
            user_id=user.id,
            day="wednesday",
            label="Mercredi",
            scheduled_date=datetime.fromisoformat("2026-04-15T07:00:00"),
            sport_type="rest",
            session_type="rest",
            session_title="Repos protecteur",
            session_goal="Assimiler",
            session_note="",
            session_description="",
            duration_min=None,
            intensity="easy",
            load_score=0,
            priority="Protection",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        db.add_all([target, recovery])
        db.commit()
        db.refresh(target)

        result = apply_decisions_for_user(
            db,
            user=user,
            decisions=[
                MutationDecision(
                    mutation_type="move_session",
                    target_session_id=target.id,
                    target_date="2026-04-15",
                    rationale="indispo",
                    fitmas_message="Je deplace.",
                )
            ],
        )

        db.refresh(target)
        events = db.query(s.PlanMutationEventRecord).all()

        db.refresh(recovery)

        assert result is not None
        assert result.applied_count == 1
        assert result.event_count == 1
        assert target.scheduled_date.date().isoformat() == "2026-04-15"
        assert recovery.scheduled_date.date().isoformat() == "2026-04-13"
        assert events[0].command_type == "move_session"
    finally:
        db.close()
