"""Materialize an isolated Runtime V0 DB from the real FitMAS app database.

This is the read-side adapter for the app-vs-V0 comparison. It snapshots the
real app state for one user at a point in time and writes it into a fresh,
isolated V0 SQLite DB shaped exactly like the scenario seed (`v0_*` tables).
The V0 runtime then runs unchanged against that shadow DB via SnapshotBuilder /
CommandExecutor, so the comparison never touches the real database.

Mapped today (the world state the coach reasons over):
  scheduled_sessions -> v0_scheduled_sessions  (plan)
  activities         -> v0_activities          (recent training)
  user_facts         -> v0_facts               (active memory facts)

Deferred (documented follow-ups, kept empty for now):
  - conversation_state / pending_confirmations: conversational continuity
  - command history (plan_mutation_events -> v0_command_events): last_execution
    /last_plan event context, needed for execution-correction style turns.

Importance mapping (the agreed fairness knob): the real app's `priority` is a
free-text *theme* label (Socle aerobie, Sortie longue, Seance cle, Recup active,
...), not an importance tier, so `_v0_priority` reads the structured fields
instead. An explicit "cle" (key) label always wins; otherwise a stable, high-load
session is the week's anchor (key) and a flexible, low-load session is droppable
(optional); everything else is secondary. This keeps key-session comparisons fair
without trusting the free-text label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Importing the orm package registers every ORM model on Base so the mappers
# (and their relationships) resolve when we query individual entities.
from fitmas.core import orm  # noqa: F401
from fitmas.core.orm.execution import Activity
from fitmas.core.orm.memory import UserFact
from fitmas.core.orm.planning import ScheduledSession
from fitmas.runtime_v0.db import connect, reset_db

_VALID_FACT_KINDS = frozenset({"preference", "health", "availability", "constraint", "goal"})
_VALID_ACTIVITY_SOURCES = frozenset({"strava", "manual"})

# Importance is read from flexibility + load_score (see module docstring). These
# thresholds match the app's 1-3 load scale: a stable session at the top of the
# scale anchors the week; a flexible session at the bottom is droppable.
_KEY_LOAD_FLOOR = 3
_OPTIONAL_LOAD_CEILING = 1

_STATUS_MAP = {
    "done": "done",
    "skipped": "skipped",
    "missed": "skipped",
    "partial": "partial",
    "planned": "planned",
    "adapted": "planned",
}


def materialize_v0_db(
    real_db_path: Path,
    user_id: int,
    as_of: datetime,
    out_db_path: Path,
) -> Path:
    """Read the real app DB for `user_id` and write a fresh V0 DB at `out_db_path`.

    `as_of` decides which facts count as active and is the snapshot's reference
    instant. The full session/activity history for the user is materialized; the
    V0 SnapshotBuilder applies its own date windows at read time.
    """
    as_of = _ensure_tz(as_of)
    reset_db(out_db_path)
    engine = create_engine(f"sqlite:///{real_db_path}")
    try:
        with Session(engine) as session:
            sessions = list(session.scalars(select(ScheduledSession).where(ScheduledSession.user_id == user_id)))
            activities = list(session.scalars(select(Activity).where(Activity.user_id == user_id)))
            facts = [
                fact
                for fact in session.scalars(select(UserFact).where(UserFact.user_id == user_id))
                if _fact_is_active(fact, as_of)
            ]
    finally:
        engine.dispose()

    with connect(out_db_path) as connection:
        for session_row in sessions:
            _insert_session(connection, session_row)
        for activity in activities:
            _insert_activity(connection, activity)
        for fact in facts:
            _insert_fact(connection, fact)
        connection.commit()
    return out_db_path


def _insert_session(connection, row: ScheduledSession) -> None:
    connection.execute(
        """
        insert into v0_scheduled_sessions
            (id, user_id, date, sport, title, duration_min, intensity_label, priority, status, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.user_id,
            _date_text(row.scheduled_date),
            row.sport_type or "running",
            row.session_title or row.label or "",
            int(row.duration_min or 0),
            row.intensity or "easy",
            _v0_priority(row.priority, row.flexibility, row.load_score),
            _v0_status(row.completion_status),
            _datetime_text(row.updated_at),
        ),
    )


def _insert_activity(connection, row: Activity) -> None:
    connection.execute(
        """
        insert into v0_activities (id, user_id, date, sport, duration_min, distance_km, notes, source)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.user_id,
            _date_text(row.started_at or row.created_at),
            row.sport_type or "running",
            int(row.duration_min or 0),
            (row.distance_m / 1000.0) if row.distance_m is not None else None,
            row.note or None,
            row.source if row.source in _VALID_ACTIVITY_SOURCES else "manual",
        ),
    )


def _insert_fact(connection, row: UserFact) -> None:
    connection.execute(
        """
        insert into v0_facts (id, user_id, kind, text, confidence, created_at, expires_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.user_id,
            _v0_fact_kind(row.category),
            row.value or row.key or "",
            float(row.confidence if row.confidence is not None else 0.7),
            _datetime_text(row.created_at),
            _datetime_text(row.expires_at) if row.expires_at is not None else None,
        ),
    )


def _fact_is_active(fact: UserFact, as_of: datetime) -> bool:
    if not bool(fact.active):
        return False
    if (fact.status or "open").strip().lower() == "resolved":
        return False
    expires_at = fact.expires_at
    if expires_at is not None and _ensure_tz(expires_at) <= as_of:
        return False
    return True


def _v0_priority(priority: str | None, flexibility: str | None, load_score: int | None) -> str:
    """Map a real session to V0's key/secondary/optional importance tier.

    The free-text `priority` label is only trusted for an explicit "cle" (key)
    marker; the tier otherwise comes from the structured fields. See the module
    docstring for why this is the agreed fairness mapping.
    """
    label = (priority or "").strip().lower()
    if "clé" in label or "cle" in label.split():
        return "key"
    movability = (flexibility or "stable").strip().lower()
    load = int(load_score or 0)
    if movability == "stable" and load >= _KEY_LOAD_FLOOR:
        return "key"
    if movability == "flexible" and load <= _OPTIONAL_LOAD_CEILING:
        return "optional"
    return "secondary"


def _v0_status(real_status: str | None) -> str:
    return _STATUS_MAP.get((real_status or "planned").strip().lower(), "planned")


def _v0_fact_kind(category: str | None) -> str:
    value = (category or "").strip().lower()
    return value if value in _VALID_FACT_KINDS else "constraint"


def _date_text(value: datetime | date | None) -> str:
    if value is None:
        raise ValueError("cannot derive a date from a null timestamp")
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_tz(value).isoformat()


def _ensure_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
