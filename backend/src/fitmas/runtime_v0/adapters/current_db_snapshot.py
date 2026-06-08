"""Materialize an isolated Runtime V0 DB from the real FitMAS app database.

Read-side snapshot adapter (real DB -> isolated V0 world). It snapshots the
real app state for one user at a point in time and writes it into a fresh,
isolated V0 SQLite DB shaped exactly like the scenario seed (`v0_*` tables).
The V0 runtime then runs unchanged against that shadow DB via SnapshotBuilder /
CommandExecutor, so the runtime never touches the real database. Used by the
eval comparison today; the couche-2 seed and dogfood paths next.

Lives under `runtime_v0/adapters/` (the legacy bridge): it MAY import the core
ORM; the V0 core never imports it. See tests/runtime_v0/test_import_boundaries.

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
from enum import StrEnum
import json
from pathlib import Path
import re
import sqlite3

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Importing the orm package registers every ORM model on Base so the mappers
# (and their relationships) resolve when we query individual entities.
from fitmas.legacy.core import orm  # noqa: F401
from fitmas.legacy.core.orm.execution import Activity
from fitmas.legacy.core.orm.memory import UserFact
from fitmas.legacy.core.orm.planning import ScheduledSession
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

_APP_GROUNDING_SESSION_RE = re.compile(
    r"^- (?P<date>\d{4}-\d{2}-\d{2}) \([^)]+\) "
    r"id=(?P<id>\d+) (?P<sport>\S+) "
    r'"(?P<title>.*?)"'
    r"(?: (?P<duration>\d+)min)? "
    r"intensity=(?P<intensity>\S+) "
    r"\[(?P<status>[^\]]+)\] "
    r"slot=(?P<slot>\S+)"
)


class SnapshotSource(StrEnum):
    """How a materialized V0 DB was produced — provenance, not core state.

    The V0 core is blind to this: it just reads a v0_* DB and cannot tell where
    the rows came from. Only the eval / benchmark layer cares, because it decides
    whether a past-turn comparison is a *faithful* replay or merely approximate.

    Single source of truth for the constant so the benchmark's faithfulness guard
    can never drift from a duplicated string literal.
    """

    # Faithful as-of replay: the plan rows the app actually had in its prompt at
    # the turn (captured grounding lines). Safe to score a past turn against.
    CONVERSATION_CONTEXT = "conversation_context"
    # Live snapshot of the mutable DB now. Fine for "start a sim from the real
    # world today"; NOT a faithful replay of a past turn — do not score against it.
    CURRENT_STATE = "current_state"


@dataclass(frozen=True)
class MaterializedV0Snapshot:
    path: Path
    source: SnapshotSource
    session_count: int


@dataclass(frozen=True)
class CapturedSession:
    id: int
    user_id: int
    date: str
    sport: str
    title: str
    duration_min: int
    intensity_label: str
    priority: str
    status: str
    updated_at: str | None = None


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
            sessions = [
                session_row
                for session_row in session.scalars(select(ScheduledSession).where(ScheduledSession.user_id == user_id))
                if _row_exists_at(getattr(session_row, "created_at", None), as_of)
            ]
            activities = [
                activity
                for activity in session.scalars(select(Activity).where(Activity.user_id == user_id))
                if _activity_exists_at(activity, as_of)
            ]
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


def materialize_v0_db_for_turn(
    real_db_path: Path,
    turn_id: int,
    out_db_path: Path,
) -> MaterializedV0Snapshot:
    """Materialize the V0 DB for a specific real conversation turn.

    Real `scheduled_sessions` is mutable. For app-vs-V0 replay, provider
    judgment must use the plan that was in the app prompt at the turn, not the
    table after later confirmations. When the turn stores app grounding lines,
    this function uses those machine-generated plan rows as the session source.
    If no captured plan is available, it falls back to the current DB snapshot
    and labels the source accordingly.
    """
    turn = _load_turn_context(real_db_path, turn_id)
    as_of = _parse_datetime(turn["created_at"])
    path = materialize_v0_db(real_db_path, int(turn["user_id"]), as_of, out_db_path)

    captured = _captured_sessions_from_context(
        _loads_json_object(turn["context_json"]),
        user_id=int(turn["user_id"]),
    )
    if not captured:
        return MaterializedV0Snapshot(path=path, source=SnapshotSource.CURRENT_STATE, session_count=0)

    count = _replace_sessions_with_captured_context(path, int(turn["user_id"]), captured)
    return MaterializedV0Snapshot(path=path, source=SnapshotSource.CONVERSATION_CONTEXT, session_count=count)


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


def _insert_captured_session(connection, row: CapturedSession) -> None:
    connection.execute(
        """
        insert into v0_scheduled_sessions
            (id, user_id, date, sport, title, duration_min, intensity_label, priority, status, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.user_id,
            row.date,
            row.sport,
            row.title,
            row.duration_min,
            row.intensity_label,
            row.priority,
            row.status,
            row.updated_at or f"{row.date}T00:00:00+00:00",
        ),
    )


def _load_turn_context(real_db_path: Path, turn_id: int) -> dict:
    connection = sqlite3.connect(real_db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            select id, user_id, created_at, context_json
            from conversation_turns
            where id = ?
            """,
            (turn_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"conversation_turn_not_found:{turn_id}")
    return dict(row)


def _replace_sessions_with_captured_context(
    db_path: Path,
    user_id: int,
    captured: tuple[CapturedSession, ...],
) -> int:
    with connect(db_path) as connection:
        defaults = {
            int(row["id"]): {
                "updated_at": row["updated_at"],
            }
            for row in connection.execute(
                "select id, updated_at from v0_scheduled_sessions where user_id = ?",
                (user_id,),
            ).fetchall()
        }
        connection.execute("delete from v0_scheduled_sessions where user_id = ?", (user_id,))
        for row in captured:
            default = defaults.get(row.id, {})
            _insert_captured_session(
                connection,
                CapturedSession(
                    id=row.id,
                    user_id=row.user_id,
                    date=row.date,
                    sport=row.sport,
                    title=row.title,
                    duration_min=row.duration_min,
                    intensity_label=row.intensity_label,
                    priority=row.priority,
                    status=row.status,
                    updated_at=default.get("updated_at") or row.updated_at,
                ),
            )
        connection.commit()
    return len(captured)


def _captured_sessions_from_context(context: dict, user_id: int) -> tuple[CapturedSession, ...]:
    grounding = context.get("grounding")
    if not isinstance(grounding, dict):
        return ()
    lines = grounding.get("lines")
    if not isinstance(lines, list):
        return ()
    rows: list[CapturedSession] = []
    for line in lines:
        if not isinstance(line, str):
            continue
        parsed = _captured_session_from_grounding_line(line, user_id)
        if parsed is not None:
            rows.append(parsed)
    rows.sort(key=lambda row: (row.date, row.id))
    return tuple(rows)


def _captured_session_from_grounding_line(line: str, user_id: int) -> CapturedSession | None:
    # This parses app-generated grounding rows, never free user text. It is an
    # eval adapter so the benchmark can replay the exact world the app prompted.
    match = _APP_GROUNDING_SESSION_RE.match(line.strip())
    if match is None:
        return None
    values = match.groupdict()
    slot = values["slot"]
    return CapturedSession(
        id=int(values["id"]),
        user_id=user_id,
        date=values["date"],
        sport=_v0_sport(values["sport"]),
        title=values["title"],
        duration_min=int(values["duration"] or 0),
        intensity_label=values["intensity"],
        priority=_priority_from_slot(slot),
        status=_v0_status(values["status"]),
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
    if not _row_exists_at(fact.created_at, as_of):
        return False
    valid_from = getattr(fact, "valid_from", None)
    if valid_from is not None and _ensure_tz(valid_from) > as_of:
        return False
    valid_until = getattr(fact, "valid_until", None)
    if valid_until is not None and _ensure_tz(valid_until) <= as_of:
        return False
    expires_at = fact.expires_at
    if expires_at is not None and _ensure_tz(expires_at) <= as_of:
        return False
    resolved_at = getattr(fact, "resolved_at", None)
    if resolved_at is not None:
        return _ensure_tz(resolved_at) > as_of
    if not bool(fact.active):
        return False
    if (fact.status or "open").strip().lower() == "resolved":
        return False
    return True


def _activity_exists_at(activity: Activity, as_of: datetime) -> bool:
    reference = activity.started_at or activity.created_at
    return _row_exists_at(reference, as_of)


def _row_exists_at(created_at: datetime | None, as_of: datetime) -> bool:
    if created_at is None:
        return True
    return _ensure_tz(created_at) <= as_of


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


def _v0_sport(value: str | None) -> str:
    sport = (value or "running").strip().lower()
    aliases = {"run": "running", "bike": "cycling", "velo": "cycling", "vélo": "cycling"}
    return aliases.get(sport, sport)


def _priority_from_slot(slot: str | None) -> str:
    value = (slot or "").strip().lower()
    if value == "free_flexible":
        return "optional"
    return "secondary"


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


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return _ensure_tz(value)
    normalized = str(value).replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    return _ensure_tz(datetime.fromisoformat(normalized))


def _loads_json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
