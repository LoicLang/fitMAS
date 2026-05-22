from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ORM = SRC / "core" / "orm"
SCHEMA = SRC / "schema.py"

EXPECTED_ORM_OWNER_CLASSES = {
    ORM / "user.py": {
        "User",
        "UserConstraint",
        "UserPreference",
        "UserSport",
    },
    ORM / "memory.py": {
        "UserFact",
        "WorkingMemoryEntry",
        "UserPattern",
        "MemoryMutationEventRecord",
    },
    ORM / "execution.py": {"Activity"},
    ORM / "integrations.py": {"StravaConnection"},
    ORM / "planning.py": {
        "WeeklyPlan",
        "ScheduledSession",
        "DayPlan",
        "ChangeNote",
        "WatchItem",
        "PlanMutationEventRecord",
        "PlanningDecisionRecord",
    },
    ORM / "coaching.py": {
        "CoachMessage",
        "ConversationTurnRecord",
        "PendingMutationConfirmation",
        "AdaptationEventRecord",
    },
    ORM / "athlete.py": {
        "FitnessSnapshotRecord",
        "ReadinessSnapshotRecord",
    },
}

EXPECTED_TABLES = {
    "users",
    "user_constraints",
    "user_preferences",
    "user_sports",
    "user_facts",
    "working_memory_entries",
    "user_patterns",
    "activities",
    "strava_connections",
    "weekly_plans",
    "scheduled_sessions",
    "day_plans",
    "change_notes",
    "watch_items",
    "coach_messages",
    "conversation_turns",
    "pending_mutation_confirmations",
    "plan_mutation_events",
    "memory_mutation_events",
    "adaptation_events",
    "fitness_snapshots",
    "readiness_snapshots",
    "planning_decisions",
}


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_13d_orm_records_live_in_core_orm_owner_modules() -> None:
    for path, expected in EXPECTED_ORM_OWNER_CLASSES.items():
        assert _class_names(path) == expected


def test_13d_root_schema_is_reexport_facade_only() -> None:
    source = SCHEMA.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCHEMA))

    assert not [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    assert "from fitmas.core.orm import" in source


def test_13d_core_orm_import_registers_same_tables() -> None:
    from fitmas.core import orm  # noqa: F401
    from fitmas.core.db import Base

    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_13d_core_orm_owner_import_resolves_records() -> None:
    from fitmas.core import orm as s

    assert s.User.__tablename__ == "users"
    assert s.ScheduledSession.__tablename__ == "scheduled_sessions"
    assert s.PlanningDecisionRecord.__tablename__ == "planning_decisions"


def test_13d_base_metadata_creates_expected_tables() -> None:
    from fitmas.core import orm  # noqa: F401
    from fitmas.core.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    assert set(Base.metadata.tables) == EXPECTED_TABLES
