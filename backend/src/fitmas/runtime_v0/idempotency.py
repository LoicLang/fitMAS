from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from fitmas.runtime_v0.db import connect

@dataclass(frozen=True)
class EventLock:
    turn_id: str
    existing: bool

def acquire_event_lock(db_path: Path, event_id: str, turn_id: str) -> EventLock:
    with connect(db_path) as connection:
        try:
            connection.execute(
                "insert into v0_idempotency_locks (event_id, turn_id) values (?, ?)",
                (event_id, turn_id),
            )
            connection.commit()
            return EventLock(turn_id, False)
        except sqlite3.IntegrityError:
            row = connection.execute(
                "select turn_id from v0_idempotency_locks where event_id = ?",
                (event_id,),
            ).fetchone()
            return EventLock(row["turn_id"], True)
