from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.memory_patterns import derive_pattern_payloads


@dataclass(frozen=True, slots=True)
class MemoryMaintenanceResult:
    users_processed: int = 0
    working_entries_archived: int = 0
    patterns_upserted: int = 0
    patterns_archived: int = 0


def run_memory_maintenance(
    db: Session,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
) -> MemoryMaintenanceResult:
    query = db.query(s.User).order_by(s.User.id.asc())
    if user_id is not None:
        query = query.filter(s.User.id == user_id)
    users = query.all()

    result = MemoryMaintenanceResult()
    for user in users:
        archived_working = repo.purge_expired_working_memory(db, user.id)
        pattern_payloads = derive_pattern_payloads(
            timezone_name=user.timezone,
            user_messages=repo.get_messages(db, user.id)[-200:],
            activities=repo.get_activities(db, user.id, limit=500),
            adaptation_events=repo.get_recent_adaptation_events(db, user.id, limit=80),
            now=now,
        )
        upserted, archived_patterns = repo.sync_user_patterns(db, user.id, pattern_payloads)
        result = MemoryMaintenanceResult(
            users_processed=result.users_processed + 1,
            working_entries_archived=result.working_entries_archived + archived_working,
            patterns_upserted=result.patterns_upserted + upserted,
            patterns_archived=result.patterns_archived + archived_patterns,
        )
    return result
