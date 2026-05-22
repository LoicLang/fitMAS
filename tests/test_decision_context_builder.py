from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest
from fitmas.domain.planning import repository as planning_repo
from fitmas.domain.planning import template_repository as template_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-decision-context-", suffix=".db"))

from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas import schema as s
from fitmas.decision import InputEvent
from fitmas.decision.context_builder import (
    ContextBuilderInput,
    DecisionContextBuilder,
    DecisionContextUserNotFoundError,
)
from fitmas.core.time_context import DAY_KEYS, day_label_fr, get_local_now


def setup_function() -> None:
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def test_context_builder_raises_when_event_user_does_not_exist() -> None:
    db = SessionLocal()
    try:
        event = InputEvent(
            id="evt_missing",
            user_id=999,
            source="telegram",
            type="user_message",
            text="hello",
            payload={},
            occurred_at=datetime(2026, 5, 14, 6, 30, tzinfo=timezone.utc),
        )

        with pytest.raises(DecisionContextUserNotFoundError):
            DecisionContextBuilder(db).build(ContextBuilderInput(event=event))
    finally:
        db.close()


def _plan_day(day_key: str) -> dict:
    return {
        "day": day_key,
        "label": day_label_fr(day_key, capitalize=True),
        "sport_type": "running",
        "session_type": "easy",
        "session_title": "Footing facile",
        "session_goal": "Relancer propre",
        "session_note": "",
        "session_description": "Footing Z2",
        "duration_min": 40,
        "intensity": "easy",
        "load_score": 2,
        "priority": "Normal",
        "nutrition_focus": "",
        "flexibility": "flexible",
        "completion_status": "planned",
    }


def test_context_builder_builds_canonical_context_from_scheduled_runtime_truth() -> None:
    db = SessionLocal()
    try:
        user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            coach_name="FitMAS",
            coach_style="direct",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        now = datetime(2026, 5, 14, 6, 30, tzinfo=timezone.utc)
        local_now = get_local_now(user.timezone, now=now)
        today_key = DAY_KEYS[local_now.weekday()]
        plan_day = _plan_day(today_key)
        template_repo.replace_plan(
            db,
            user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=user.timezone,
            now=now,
            days=[plan_day],
        )
        session = planning_repo.get_scheduled_sessions(db, user.id)[0]
        session.scheduled_date = local_now.replace(hour=8, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        db.commit()
        db.refresh(session)
        event = InputEvent(
            id="evt_1",
            user_id=user.id,
            source="telegram",
            type="user_message",
            text="j'ai quoi aujourd'hui ?",
            payload={"client_message_key": "telegram:1"},
            occurred_at=now,
        )

        context = DecisionContextBuilder(db).build(ContextBuilderInput(event=event, now=now))

        assert context.user.id == user.id
        assert context.local_time.timezone_name == "Europe/Paris"
        assert context.plan.scheduled_sessions == (session,)
        assert context.plan.planning_contract is not None
        assert context.plan.week_mission is not None
        assert context.execution.activities == ()
        assert context.memory.active_memory == ()
        assert context.athlete.profile_snapshot is not None
        assert context.athlete.calibration_status is not None
        assert context.execution.recent_reality is not None
        assert context.weekly_digest.week_summary["total_sessions"] == 1
        assert context.weekly_digest.coach_reading.strip()
    finally:
        db.close()
