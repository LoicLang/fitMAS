"""Validate the real-app -> Runtime V0 snapshot adapter.

Builds a throwaway "real app" SQLite DB with the production ORM schema, seeds one
user's plan/activity/fact rows, materializes an isolated V0 DB from it, and runs
the unchanged V0 SnapshotBuilder over the result. The assertions check that the
world the coach reasons over matches the real app state after vocab
normalization (priority tier, status, fact kind, meters -> km).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Importing the orm package registers every model on Base before create_all.
from fitmas.core import orm  # noqa: F401
from fitmas.core.db import Base
from fitmas.core.orm.coaching import ConversationTurnRecord
from fitmas.core.orm.execution import Activity
from fitmas.core.orm.memory import UserFact
from fitmas.core.orm.planning import ScheduledSession
from fitmas.runtime_v0.snapshot import SnapshotBuilder

from scripts.v0_eval.real_snapshot import materialize_v0_db, materialize_v0_db_for_turn

USER_ID = 42
OTHER_USER_ID = 99
AS_OF = datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc)


def _seed_real_db(path) -> None:
    """Create the production schema and seed one user's rows (no User row: the
    standalone engine does not enable the foreign_keys PRAGMA, matching core.db)."""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            # Plan: four real-shaped sessions inside the current-plan window, one
            # per importance tier under the structured mapping:
            #   "Séance clé" label -> key (label wins)
            #   stable + load 3 (long run, no "clé") -> key (structured rule)
            #   flexible + load 2 -> secondary
            #   flexible + load 1 (recovery) -> optional
            session.add(
                ScheduledSession(
                    id=60,
                    user_id=USER_ID,
                    day="thursday",
                    label="J+1",
                    scheduled_date=AS_OF + timedelta(days=1),
                    sport_type="running",
                    session_title="Fractionné côtes",
                    session_goal="Séance clé trail",
                    duration_min=55,
                    intensity="hard",
                    load_score=3,
                    priority="Séance clé",
                    flexibility="stable",
                    completion_status="planned",
                    created_at=AS_OF - timedelta(days=7),
                )
            )
            session.add(
                ScheduledSession(
                    id=61,
                    user_id=USER_ID,
                    day="sunday",
                    label="J+2",
                    scheduled_date=AS_OF + timedelta(days=2),
                    sport_type="running",
                    session_title="Sortie longue trail",
                    session_goal="Volume en terrain trail",
                    duration_min=85,
                    intensity="moderate",
                    load_score=3,
                    priority="Sortie longue",
                    flexibility="stable",
                    completion_status="planned",
                    created_at=AS_OF - timedelta(days=7),
                )
            )
            session.add(
                ScheduledSession(
                    id=62,
                    user_id=USER_ID,
                    day="monday",
                    label="J+3",
                    scheduled_date=AS_OF + timedelta(days=3),
                    sport_type="cycling",
                    session_title="Sortie vélo endurance",
                    session_goal="Volume aérobie sans forcer",
                    duration_min=60,
                    intensity="easy",
                    load_score=2,
                    priority="Socle aérobie",
                    flexibility="flexible",
                    completion_status="planned",
                    created_at=AS_OF - timedelta(days=7),
                )
            )
            session.add(
                ScheduledSession(
                    id=63,
                    user_id=USER_ID,
                    day="friday",
                    label="J+4",
                    scheduled_date=AS_OF + timedelta(days=4),
                    sport_type="swimming",
                    session_title="Natation technique",
                    session_goal="Récupération active",
                    duration_min=45,
                    intensity="easy",
                    load_score=1,
                    priority="Récup active",
                    flexibility="flexible",
                    completion_status="planned",
                    created_at=AS_OF - timedelta(days=7),
                )
            )
            # A future-created session must not leak into an as-of replay.
            session.add(
                ScheduledSession(
                    id=64,
                    user_id=USER_ID,
                    day="tuesday",
                    label="future",
                    scheduled_date=AS_OF + timedelta(days=5),
                    sport_type="running",
                    session_title="Future session",
                    session_goal="Should not exist yet",
                    duration_min=30,
                    intensity="easy",
                    load_score=1,
                    priority="Récup active",
                    flexibility="flexible",
                    completion_status="planned",
                    created_at=AS_OF + timedelta(minutes=1),
                )
            )
            # A session belonging to another user must never leak in.
            session.add(
                ScheduledSession(
                    id=70,
                    user_id=OTHER_USER_ID,
                    day="thursday",
                    label="J+1",
                    scheduled_date=AS_OF + timedelta(days=1),
                    sport_type="running",
                    session_title="Pas la mienne",
                    session_goal="Autre user",
                    duration_min=60,
                    intensity="hard",
                    load_score=3,
                    priority="Séance clé",
                    flexibility="stable",
                    completion_status="planned",
                    created_at=AS_OF - timedelta(days=7),
                )
            )

            # Activity: a Strava run yesterday, distance in meters -> km.
            session.add(
                Activity(
                    id=7,
                    user_id=USER_ID,
                    source="strava",
                    sport_type="running",
                    title="Sortie longue",
                    duration_min=70,
                    distance_m=12000.0,
                    note="jambes lourdes",
                    started_at=AS_OF - timedelta(days=1),
                )
            )
            session.add(
                Activity(
                    id=8,
                    user_id=USER_ID,
                    source="manual",
                    sport_type="running",
                    title="Future same-day activity",
                    duration_min=20,
                    started_at=AS_OF + timedelta(minutes=10),
                )
            )

            # Facts: one active health fact survives; an inactive one is dropped.
            session.add(
                UserFact(
                    id=3,
                    user_id=USER_ID,
                    category="health",
                    key="blessure_genou",
                    value="Douleur genou droit en descente",
                    confidence=0.9,
                    active=True,
                    status="open",
                    created_at=AS_OF - timedelta(days=1),
                )
            )
            session.add(
                UserFact(
                    id=5,
                    user_id=USER_ID,
                    category="health",
                    key="future_fatigue",
                    value="Fatigue déclarée après le tour",
                    confidence=0.9,
                    active=True,
                    status="open",
                    created_at=AS_OF + timedelta(minutes=10),
                )
            )
            session.add(
                UserFact(
                    id=4,
                    user_id=USER_ID,
                    category="preference",
                    key="vieux_fait",
                    value="préférence obsolète",
                    active=False,
                    status="open",
                    created_at=AS_OF - timedelta(days=1),
                )
            )
            session.commit()
    finally:
        engine.dispose()


def test_materialize_v0_db_reflects_real_app_state(tmp_path):
    real_db = tmp_path / "real.db"
    v0_db = tmp_path / "v0.db"
    _seed_real_db(real_db)

    out = materialize_v0_db(real_db, USER_ID, AS_OF, v0_db)
    assert out == v0_db

    snapshot = SnapshotBuilder(v0_db).build(USER_ID, AS_OF)

    # Plan: all four of this user's sessions land in the current-plan window,
    # ordered by date; the other user's session never leaks in.
    assert [s.id for s in snapshot.current_plan] == [60, 61, 62, 63]
    key_session = snapshot.current_plan[0]
    assert key_session.sport == "running"
    assert key_session.title == "Fractionné côtes"
    assert key_session.duration_min == 55
    assert key_session.intensity_label == "hard"
    assert key_session.status == "planned"
    # Tier comes from the structured mapping, not the free-text label: "Séance clé"
    # -> key (label), stable+load3 long run -> key (structured), flexible+load2 ->
    # secondary, flexible+load1 recovery -> optional.
    assert [s.priority for s in snapshot.current_plan] == ["key", "key", "secondary", "optional"]

    # Activity: the Strava run is in the recent window, meters converted to km.
    assert [a.id for a in snapshot.recent_activities] == [7]
    activity = snapshot.recent_activities[0]
    assert activity.source == "strava"
    assert activity.sport == "running"
    assert activity.duration_min == 70
    assert activity.distance_km == pytest.approx(12.0)
    assert activity.notes == "jambes lourdes"

    # Facts: only the active, unresolved health fact survives the active filter.
    assert [f.id for f in snapshot.active_facts] == [3]
    fact = snapshot.active_facts[0]
    assert fact.kind == "health"
    assert fact.text == "Douleur genou droit en descente"
    assert fact.confidence == pytest.approx(0.9)


def test_materialize_v0_db_for_turn_uses_captured_app_context_over_current_mutable_plan(tmp_path):
    real_db = tmp_path / "real.db"
    v0_db = tmp_path / "v0.db"
    engine = create_engine(f"sqlite:///{real_db}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            # Current mutable state after a later confirmation: this is NOT what
            # the coach saw at turn #151 time and must not drive provider judgment.
            session.add(
                ScheduledSession(
                    id=67,
                    user_id=USER_ID,
                    day="monday",
                    label="J+0",
                    scheduled_date=datetime(2026, 5, 25, 5, 50, tzinfo=timezone.utc),
                    sport_type="strength",
                    session_title="Mobilite facile",
                    session_goal="Garder le mouvement",
                    duration_min=36,
                    intensity="easy",
                    load_score=1,
                    priority="Recup active",
                    flexibility="flexible",
                    completion_status="planned",
                )
            )
            session.add(
                ScheduledSession(
                    id=68,
                    user_id=USER_ID,
                    day="tuesday",
                    label="J+1",
                    scheduled_date=datetime(2026, 5, 26, 5, 50, tzinfo=timezone.utc),
                    sport_type="running",
                    session_title="Footing endurance 40min zone 1 - version facile",
                    session_goal="Endurance facile",
                    duration_min=40,
                    intensity="easy",
                    load_score=2,
                    priority="Socle aérobie",
                    flexibility="stable",
                    completion_status="done",
                )
            )
            session.add(
                ConversationTurnRecord(
                    id=151,
                    user_id=USER_ID,
                    user_message="Échange aujourd’hui et demain s’il te plaît",
                    assistant_message="Tu confirmes ?",
                    response_mode="plan_adaptation_pending_confirmation",
                    mutation_type="plan_change",
                    mutation_applied=False,
                    pending_confirmation=True,
                    pending_confirmation_id=13,
                    context_json=json.dumps(
                        {
                            "grounding": {
                                "lines": [
                                    "LocalDate: 2026-05-25 (lundi) timezone=Europe/Paris",
                                    "PlanWindow:",
                                    '- 2026-05-25 (lundi) id=67 running "Footing endurance 40min zone 1 - version facile" 40min intensity=easy [planned] slot=training',
                                    '- 2026-05-26 (mardi) id=68 strength "Mobilite facile" 36min intensity=easy [planned] slot=free_flexible',
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    decision_json="{}",
                    memory_writes_json="[]",
                    created_at=datetime(2026, 5, 25, 5, 50, tzinfo=timezone.utc),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    result = materialize_v0_db_for_turn(real_db, 151, v0_db)

    assert result.source == "conversation_context"
    assert result.session_count == 2

    snapshot = SnapshotBuilder(v0_db).build(USER_ID, datetime(2026, 5, 25, 5, 50, tzinfo=timezone.utc))
    assert [
        (s.id, s.date.isoformat(), s.sport, s.title, s.duration_min, s.priority, s.status)
        for s in snapshot.current_plan
    ] == [
        (67, "2026-05-25", "running", "Footing endurance 40min zone 1 - version facile", 40, "secondary", "planned"),
        (68, "2026-05-26", "strength", "Mobilite facile", 36, "optional", "planned"),
    ]
