from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
MODELS = SRC / "models.py"
SCHEMA = SRC / "schema.py"
ORM = SRC / "core" / "orm"

EXPECTED_PYDANTIC_OWNER_CLASSES = {
    SRC / "decision" / "message_models.py": {
        "MessageRole",
        "Message",
        "Extraction",
        "MessageReply",
    },
    SRC / "domain" / "planning" / "view_models.py": {
        "DayId",
        "ChangeNote",
        "WatchItem",
        "DayPlan",
        "WeeklyPlan",
        "ScheduledSession",
        "WorkoutContentView",
    },
    SRC / "domain" / "athlete" / "view_models.py": {"Profile"},
    SRC / "domain" / "execution" / "view_models.py": {"Activity"},
    SRC / "domain" / "memory" / "view_models.py": {"UserFact", "UserPattern"},
    SRC / "app" / "api" / "read_models.py": {
        "TodayFitness",
        "RecentSportActivity",
        "TodayView",
    },
    SRC / "app" / "api" / "payloads.py": {
        "IncomingMessage",
        "MoveSessionPayload",
        "OnboardPayload",
        "OnboardPreviewPayload",
        "ManualActivityPayload",
    },
    SRC / "app" / "api" / "onboarding_models.py": {"OnboardPreview", "OnboardResult"},
}

EXPECTED_ORM_CLASSES = {
    "User",
    "UserConstraint",
    "UserPreference",
    "UserSport",
    "UserFact",
    "WorkingMemoryEntry",
    "UserPattern",
    "Activity",
    "StravaConnection",
    "WeeklyPlan",
    "ScheduledSession",
    "DayPlan",
    "ChangeNote",
    "WatchItem",
    "CoachMessage",
    "ConversationTurnRecord",
    "PendingMutationConfirmation",
    "PlanMutationEventRecord",
    "MemoryMutationEventRecord",
    "AdaptationEventRecord",
    "FitnessSnapshotRecord",
    "ReadinessSnapshotRecord",
    "PlanningDecisionRecord",
}

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


def test_13a_root_models_and_schema_are_deleted() -> None:
    assert not MODELS.exists()
    assert not SCHEMA.exists()


def test_13a_owner_modules_export_expected_pydantic_contracts() -> None:
    for path, expected in EXPECTED_PYDANTIC_OWNER_CLASSES.items():
        assert _class_names(path) == expected


def test_13a_orm_owner_modules_export_expected_records() -> None:
    discovered: set[str] = set()
    for path, expected in EXPECTED_ORM_OWNER_CLASSES.items():
        class_names = _class_names(path)
        assert class_names == expected
        discovered.update(class_names)

    assert discovered == EXPECTED_ORM_CLASSES


def test_13a_schema_registers_expected_table_names() -> None:
    from fitmas.legacy.core.db import Base
    from fitmas.legacy.core import orm  # noqa: F401

    assert set(Base.metadata.tables) == EXPECTED_TABLES
