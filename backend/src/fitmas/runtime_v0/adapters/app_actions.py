"""App-driven V0 writes (the legacy webapp bridge).

The webapp (legacy) calls these to write into the isolated V0 store **through the
official executor** (transactional, audited) — never a raw write. This is the only
runtime_v0 surface the webapp imports for writes; it mirrors strava_v0_sync.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fitmas.runtime_v0.executor import CommandEvent, CommandExecutor
from fitmas.runtime_v0.policy import LinkActivityToSessionCommand, UnlinkActivityCommand


def link_activity_to_session(v0_db_path: Path, *, user_id: int, activity_id: int, session_id: int) -> CommandEvent:
    command = LinkActivityToSessionCommand(activity_id=activity_id, session_id=session_id, evidence="app: manual link")
    events = CommandExecutor(v0_db_path).execute((command,), turn_id=f"app-link-{uuid.uuid4().hex}", user_id=user_id)
    return events[0]


def unlink_activity(v0_db_path: Path, *, user_id: int, activity_id: int) -> CommandEvent:
    command = UnlinkActivityCommand(activity_id=activity_id, evidence="app: manual unlink")
    events = CommandExecutor(v0_db_path).execute((command,), turn_id=f"app-unlink-{uuid.uuid4().hex}", user_id=user_id)
    return events[0]
