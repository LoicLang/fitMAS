from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from fitmas.runtime_v0.db import connect

STALE_LOCK_AFTER = timedelta(minutes=15)

@dataclass(frozen=True)
class EventLock:
    turn_id: str
    existing: bool
    status: str
    updated_at: datetime | None = None

def acquire_event_lock(db_path: Path, event_id: str, turn_id: str) -> EventLock:
    with connect(db_path) as connection:
        try:
            connection.execute(
                "insert into v0_idempotency_locks (event_id, turn_id, status) values (?, ?, 'running')",
                (event_id, turn_id),
            )
            connection.commit()
            return EventLock(turn_id, False, "running")
        except sqlite3.IntegrityError:
            row = connection.execute(
                "select turn_id, status, updated_at from v0_idempotency_locks where event_id = ?",
                (event_id,),
            ).fetchone()
            return EventLock(row["turn_id"], True, row["status"], _parse_db_time(row["updated_at"]))

def mark_event_lock(db_path: Path, event_id: str, status: str) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "update v0_idempotency_locks set status = ?, updated_at = CURRENT_TIMESTAMP where event_id = ?",
            (status, event_id),
        )
        connection.commit()

def lock_allows_retry(lock: EventLock, now: datetime | None = None) -> bool:
    if lock.status == "failed":
        return True
    if lock.status != "running" or lock.updated_at is None:
        return False
    checked_at = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    return lock.updated_at <= checked_at - STALE_LOCK_AFTER

def _parse_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for candidate in (value, value.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate).replace(tzinfo=None)
        except ValueError:
            continue
    return None
