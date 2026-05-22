from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"

EXPECTED_ROOT_FILES = {
    "__init__.py",
    "api.py",
    "main.py",
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


def test_13f_root_schema_file_is_deleted() -> None:
    assert not (SRC / "schema.py").exists()


def test_13f_root_contains_only_entrypoints() -> None:
    assert {path.name for path in SRC.glob("*.py")} == EXPECTED_ROOT_FILES


def test_13f_core_orm_remains_the_metadata_registry() -> None:
    from fitmas.core import orm  # noqa: F401
    from fitmas.core.db import Base

    assert set(Base.metadata.tables) == EXPECTED_TABLES
