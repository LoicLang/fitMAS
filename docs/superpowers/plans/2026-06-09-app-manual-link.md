# App manual activity↔session link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the webapp calendar, manually link a completed activity to a planned session → the session is marked `done` and the link is stored and displayed (with an undo), writing to the V0 store through the official executor.

**Architecture:** New typed executor commands (`LinkActivityToSession`, `Unlink`) write the link + status into the V0 store, audited. A thin adapter (`runtime_v0/adapters/app_actions.py`) is the only V0 bridge the legacy webapp imports. New v0-mode-only FastAPI routes call the adapter; `v0_source` surfaces the stored link; the React calendar day-panel adds the link/unlink affordance.

**Tech Stack:** Python 3.12 · sqlite3 · FastAPI · pytest · React/Vite/TypeScript.

Spec: `docs/superpowers/specs/2026-06-09-app-manual-link-design.md`. Run backend tests with `.venv/bin/python -m pytest`.

---

## File structure

- `backend/src/fitmas/runtime_v0/db.py` — add `scheduled_session_id` to the `v0_activities` schema + idempotent migration.
- `backend/src/fitmas/runtime_v0/policy.py` — two new `Command` dataclasses.
- `backend/src/fitmas/runtime_v0/executor.py` — dispatch + `_target` + two handlers + `_activity`/`_activity_or_raise`.
- `backend/src/fitmas/runtime_v0/adapters/app_actions.py` — NEW thin adapter (link/unlink → executor).
- `backend/src/fitmas/legacy/app/api/v0_source.py` — map `scheduled_session_id`; add `v0_user_id()` resolver.
- `backend/src/fitmas/legacy/app/api/routes_v0_link.py` — NEW v0-mode link/unlink endpoints.
- `backend/src/fitmas/legacy/api.py` — register the new router.
- `frontend/src/shared/api.ts` — `linkActivityToSession` / `unlinkActivity`.
- `frontend/src/features/calendar/CalendarPage.tsx` (+ `types.ts`) — link/unlink UI in the day panel.

---

# Phase 1 — Backend (provable with tests + curl, no UI)

### Task 1: Schema + migration for `v0_activities.scheduled_session_id`

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/db.py`
- Test: `tests/runtime_v0/test_activity_link_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime_v0/test_activity_link_migration.py
import sqlite3
from fitmas.runtime_v0.db import init_db


def test_init_db_adds_scheduled_session_id_to_old_activities(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    # old-shape v0_activities (no scheduled_session_id)
    con.execute(
        "create table v0_activities (id integer primary key, user_id integer, date text, "
        "sport text, duration_min integer, distance_km real, notes text, source text)"
    )
    con.commit()
    con.close()

    init_db(db)            # must add the column, idempotently
    init_db(db)

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(v0_activities)")}
    con.close()
    assert "scheduled_session_id" in cols


def test_fresh_db_has_scheduled_session_id(tmp_path):
    db = tmp_path / "fresh.db"
    init_db(db)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(v0_activities)")}
    con.close()
    assert "scheduled_session_id" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_activity_link_migration.py -v`
Expected: FAIL (`scheduled_session_id` not in cols).

- [ ] **Step 3: Implement schema + migration**

In `db.py`, add the column to the `v0_activities` CREATE TABLE in the `SCHEMA` string:
```sql
CREATE TABLE IF NOT EXISTS v0_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    sport TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    distance_km REAL,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    scheduled_session_id INTEGER
);
```
Add a migration helper and call it from `init_db` (mirror `_ensure_fact_columns`):
```python
def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        _ensure_fact_columns(connection)
        _ensure_activity_columns(connection)
        connection.commit()


def _ensure_activity_columns(connection: sqlite3.Connection) -> None:
    # Older v0 DBs predate the activity<->session link. CREATE TABLE IF NOT EXISTS
    # won't add the column, so add it here when missing.
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(v0_activities)")}
    if "scheduled_session_id" not in columns:
        connection.execute("ALTER TABLE v0_activities ADD COLUMN scheduled_session_id INTEGER")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_activity_link_migration.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/db.py tests/runtime_v0/test_activity_link_migration.py
git commit -m "feat(v0): add v0_activities.scheduled_session_id (schema + idempotent migration)"
```

---

### Task 2: Executor — Link/Unlink commands & handlers

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/policy.py` (dataclasses)
- Modify: `backend/src/fitmas/runtime_v0/executor.py` (dispatch, `_target`, handlers, helpers)
- Test: `tests/runtime_v0/test_executor_link_activity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime_v0/test_executor_link_activity.py
import sqlite3
import pytest
from fitmas.runtime_v0.db import init_db
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.policy import LinkActivityToSessionCommand, UnlinkActivityCommand

USER = 555


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute(
        "insert into v0_scheduled_sessions (id, user_id, date, sport, title, duration_min, "
        "intensity_label, priority, status) values (10, ?, '2026-06-08', 'running', 'Seuil', 45, 'hard', 'key', 'planned')",
        (USER,),
    )
    con.execute(
        "insert into v0_activities (id, user_id, date, sport, duration_min, distance_km, notes, source) "
        "values (900, ?, '2026-06-08', 'running', 50, 9.5, 'run', 'strava')",
        (USER,),
    )
    con.commit()
    con.close()


def _row(db, sql, args=()):
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    r = con.execute(sql, args).fetchone(); con.close()
    return r


def test_link_sets_fk_and_marks_session_done_and_audits(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    events = CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="app link"),),
        turn_id="app-link-1", user_id=USER,
    )
    assert events[0].status == "applied"
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] == 10
    assert _row(db, "select status from v0_scheduled_sessions where id=10")[0] == "done"
    assert _row(db, "select count(*) from v0_command_events where command_type='LinkActivityToSessionCommand'")[0] == 1


def test_unlink_clears_fk_and_reverts_session(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="link"),),
        turn_id="t1", user_id=USER,
    )
    CommandExecutor(db).execute(
        (UnlinkActivityCommand(activity_id=900, evidence="undo"),),
        turn_id="t2", user_id=USER,
    )
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] is None
    assert _row(db, "select status from v0_scheduled_sessions where id=10")[0] == "planned"


def test_link_rejects_wrong_user(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    events = CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="x"),),
        turn_id="t3", user_id=999,   # not the owner
    )
    assert events[0].status == "blocked"
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_link_activity.py -v`
Expected: FAIL (`ImportError: LinkActivityToSessionCommand`).

- [ ] **Step 3: Add the command dataclasses**

In `policy.py`, after `UpdateConversationStateCommand`:
```python
@dataclass(frozen=True)
class LinkActivityToSessionCommand(Command):
    activity_id: int
    session_id: int
    evidence: str

@dataclass(frozen=True)
class UnlinkActivityCommand(Command):
    activity_id: int
    evidence: str
```

- [ ] **Step 4: Wire dispatch, target, and handlers in `executor.py`**

Extend the import from `policy`:
```python
from fitmas.runtime_v0.policy import (
    ApplyPlanPatchCommand,
    Command,
    CorrectSessionStatusCommand,
    CreatePendingConfirmationCommand,
    LinkActivityToSessionCommand,
    ResolveMemoryFactCommand,
    ResolvePendingConfirmationCommand,
    SetSessionStatusCommand,
    UnlinkActivityCommand,
    UpdateConversationStateCommand,
    UpsertMemoryFactCommand,
)
```
In `_apply_command`, before the final `raise`:
```python
    if isinstance(command, LinkActivityToSessionCommand):
        return _apply_link_activity_to_session(command, connection, user_id)
    if isinstance(command, UnlinkActivityCommand):
        return _apply_unlink_activity(command, connection, user_id)
```
In `_target`, before the final `return "unknown", ...`:
```python
    if isinstance(command, LinkActivityToSessionCommand):
        return "activity", str(command.activity_id)
    if isinstance(command, UnlinkActivityCommand):
        return "activity", str(command.activity_id)
```
Add helpers + handlers (near `_session_or_raise`):
```python
def _activity(connection, activity_id: int) -> dict[str, Any] | None:
    row = connection.execute("select * from v0_activities where id = ?", (activity_id,)).fetchone()
    return dict(row) if row else None


def _activity_or_raise(connection, activity_id: int) -> dict[str, Any]:
    row = _activity(connection, activity_id)
    if row is None:
        raise ValueError("activity_not_found")
    return row


def _apply_link_activity_to_session(command: LinkActivityToSessionCommand, connection, user_id: int):
    activity = _activity_or_raise(connection, command.activity_id)
    session = _session_or_raise(connection, command.session_id)
    if activity["user_id"] != user_id or session["user_id"] != user_id:
        raise ValueError("not_owner")
    before = {"activity": activity, "session": session}
    connection.execute(
        "update v0_activities set scheduled_session_id = ? where id = ?",
        (command.session_id, command.activity_id),
    )
    connection.execute(
        "update v0_scheduled_sessions set status = 'done', updated_at = ? where id = ?",
        (_now_text(), command.session_id),
    )
    after = {"activity": _activity(connection, command.activity_id), "session": _session(connection, command.session_id)}
    return before, after, command.evidence


def _apply_unlink_activity(command: UnlinkActivityCommand, connection, user_id: int):
    activity = _activity_or_raise(connection, command.activity_id)
    if activity["user_id"] != user_id:
        raise ValueError("not_owner")
    session_id = activity["scheduled_session_id"]
    before = {"activity": activity, "session": _session(connection, session_id) if session_id else None}
    connection.execute(
        "update v0_activities set scheduled_session_id = null where id = ?",
        (command.activity_id,),
    )
    if session_id is not None:
        connection.execute(
            "update v0_scheduled_sessions set status = 'planned', updated_at = ? where id = ?",
            (_now_text(), session_id),
        )
    after = {"activity": _activity(connection, command.activity_id), "session": _session(connection, session_id) if session_id else None}
    return before, after, command.evidence
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_link_activity.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/policy.py backend/src/fitmas/runtime_v0/executor.py tests/runtime_v0/test_executor_link_activity.py
git commit -m "feat(v0): Link/Unlink activity<->session executor commands (audited, ownership-checked)"
```

---

### Task 3: Adapter — `app_actions.py`

**Files:**
- Create: `backend/src/fitmas/runtime_v0/adapters/app_actions.py`
- Test: `tests/runtime_v0/test_app_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime_v0/test_app_actions.py
import sqlite3
from fitmas.runtime_v0.db import init_db
from fitmas.runtime_v0.adapters.app_actions import link_activity_to_session, unlink_activity

USER = 7


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_scheduled_sessions (id,user_id,date,sport,title,duration_min,intensity_label,priority,status) "
                "values (1,?,'2026-06-08','running','Seuil',45,'hard','key','planned')", (USER,))
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
                "values (2,?,'2026-06-08','running',50,9.0,'r','strava')", (USER,))
    con.commit(); con.close()


def _val(db, sql):
    con = sqlite3.connect(db); v = con.execute(sql).fetchone()[0]; con.close(); return v


def test_link_then_unlink(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    ev = link_activity_to_session(db, user_id=USER, activity_id=2, session_id=1)
    assert ev.status == "applied"
    assert _val(db, "select scheduled_session_id from v0_activities where id=2") == 1
    assert _val(db, "select status from v0_scheduled_sessions where id=1") == "done"

    unlink_activity(db, user_id=USER, activity_id=2)
    assert _val(db, "select scheduled_session_id from v0_activities where id=2") is None
    assert _val(db, "select status from v0_scheduled_sessions where id=1") == "planned"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_app_actions.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the adapter**

```python
# backend/src/fitmas/runtime_v0/adapters/app_actions.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_app_actions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/adapters/app_actions.py tests/runtime_v0/test_app_actions.py
git commit -m "feat(v0): app_actions adapter — webapp writes link/unlink via the executor"
```

---

### Task 4: v0_source — surface the link + resolve the solo user

**Files:**
- Modify: `backend/src/fitmas/legacy/app/api/v0_source.py`
- Test: `tests/test_v0_source_link.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_v0_source_link.py
import sqlite3
import importlib
from fitmas.runtime_v0.db import init_db


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source,scheduled_session_id) "
                "values (3,77,'2026-06-08','running',50,9.0,'r','strava',12)")
    con.commit(); con.close()


def test_get_activities_exposes_scheduled_session_id(tmp_path, monkeypatch):
    db = tmp_path / "v0.db"; _seed(db)
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
    from fitmas.legacy.app.api import v0_source
    importlib.reload(v0_source)
    acts = v0_source.get_activities()
    assert acts[0].scheduled_session_id == 12
    assert v0_source.v0_user_id() == 77
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_v0_source_link.py -v`
Expected: FAIL (`scheduled_session_id` is None / `v0_user_id` missing).

- [ ] **Step 3: Map the column + add the resolver**

In `get_activities`, inside the row loop, read the column defensively and pass it to `Activity(...)`:
```python
        scheduled_session_id = row["scheduled_session_id"] if "scheduled_session_id" in keys else None
```
Add `scheduled_session_id=scheduled_session_id` to the `Activity(...)` constructor call.

Add the resolver (the V0 store is solo — one user keyed on the telegram chat id):
```python
def v0_user_id() -> int | None:
    """Resolve the single V0 user id (the store is solo)."""
    path = v0_db_path()
    if not path.exists():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "select user_id from v0_scheduled_sessions union select user_id from v0_activities limit 1"
        ).fetchone()
    return int(row["user_id"]) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_v0_source_link.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/legacy/app/api/v0_source.py tests/test_v0_source_link.py
git commit -m "feat(webapp): v0_source surfaces the activity->session link + solo user resolver"
```

---

### Task 5: Routes — `routes_v0_link.py` + register

**Files:**
- Create: `backend/src/fitmas/legacy/app/api/routes_v0_link.py`
- Modify: `backend/src/fitmas/legacy/api.py`
- Test: `tests/test_v0_link_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_v0_link_endpoint.py
import sqlite3
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fitmas.runtime_v0.db import init_db


def _app(db, monkeypatch):
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
    monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
    import importlib
    from fitmas.legacy.app.api import v0_source, routes_v0_link
    importlib.reload(v0_source)
    importlib.reload(routes_v0_link)
    app = FastAPI()
    app.include_router(routes_v0_link.router)
    return TestClient(app)


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_scheduled_sessions (id,user_id,date,sport,title,duration_min,intensity_label,priority,status) "
                "values (1,5,'2026-06-08','running','Seuil',45,'hard','key','planned')")
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
                "values (2,5,'2026-06-08','running',50,9.0,'r','strava')")
    con.commit(); con.close()


def test_link_then_unlink_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "v0.db"; _seed(db)
    client = _app(db, monkeypatch)

    r = client.post("/api/v0/activities/2/link", json={"session_id": 1})
    assert r.status_code == 200, r.text
    assert r.json()["session_status"] == "done"

    con = sqlite3.connect(db)
    assert con.execute("select scheduled_session_id from v0_activities where id=2").fetchone()[0] == 1
    con.close()

    r = client.post("/api/v0/activities/2/unlink", json={})
    assert r.status_code == 200, r.text
    assert r.json()["session_status"] == "planned"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_v0_link_endpoint.py -v`
Expected: FAIL (module `routes_v0_link` not found).

- [ ] **Step 3: Implement the routes**

```python
# backend/src/fitmas/legacy/app/api/routes_v0_link.py
"""Manual activity<->session link, V0 store only (FITMAS_APP_SOURCE=v0).

The user explicitly links a completed activity to a planned session in the calendar.
Writes go through the official V0 executor (audited) via the app_actions adapter.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fitmas.legacy.app.api.routes_app import _app_source_is_v0
from fitmas.legacy.app.api.v0_source import v0_db_path, v0_user_id, get_scheduled_sessions
from fitmas.runtime_v0.adapters.app_actions import link_activity_to_session, unlink_activity

router = APIRouter()


class LinkPayload(BaseModel):
    session_id: int


class LinkResult(BaseModel):
    activity_id: int
    session_id: int | None
    session_status: str | None


def _require_v0_user() -> int:
    if not _app_source_is_v0():
        raise HTTPException(status_code=409, detail="Link is only available in V0 app mode")
    user_id = v0_user_id()
    if user_id is None:
        raise HTTPException(status_code=404, detail="No V0 user yet")
    return user_id


def _session_status(session_id: int) -> str | None:
    for s in get_scheduled_sessions():
        if s.id == session_id:
            return s.completion_status
    return None


@router.post("/api/v0/activities/{activity_id}/link", response_model=LinkResult)
def link(activity_id: int, payload: LinkPayload) -> LinkResult:
    user_id = _require_v0_user()
    event = link_activity_to_session(v0_db_path(), user_id=user_id, activity_id=activity_id, session_id=payload.session_id)
    if event.status != "applied":
        raise HTTPException(status_code=400, detail=event.reason)
    return LinkResult(activity_id=activity_id, session_id=payload.session_id, session_status=_session_status(payload.session_id))


@router.post("/api/v0/activities/{activity_id}/unlink", response_model=LinkResult)
def unlink(activity_id: int) -> LinkResult:
    user_id = _require_v0_user()
    event = unlink_activity(v0_db_path(), user_id=user_id, activity_id=activity_id)
    if event.status != "applied":
        raise HTTPException(status_code=400, detail=event.reason)
    linked = event.before.get("session") if isinstance(event.before, dict) else None
    session_id = linked.get("id") if isinstance(linked, dict) else None
    return LinkResult(activity_id=activity_id, session_id=session_id, session_status=_session_status(session_id) if session_id else None)
```

Register it in `api.py` (import near the other route imports, include near the others):
```python
from fitmas.legacy.app.api.routes_v0_link import router as v0_link_router
...
app.include_router(v0_link_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_v0_link_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full proven-core suite (no regression)**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q`
Expected: all pass (prior 266 + the new executor/adapter tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/legacy/app/api/routes_v0_link.py backend/src/fitmas/legacy/api.py tests/test_v0_link_endpoint.py
git commit -m "feat(webapp): v0-mode endpoints to link/unlink an activity to a session"
```

- [ ] **Step 7: Manual curl smoke (optional, against a local v0 DB)**

```bash
FITMAS_APP_SOURCE=v0 FITMAS_V0_DB_PATH=fitmas_v0.db ./scripts/dev   # or however the API is started
curl -XPOST localhost:8033/api/v0/activities/<aid>/link -H 'content-type: application/json' -d '{"session_id":<sid>}'
```

---

# Phase 2 — Calendar UI

### Task 6: API client + confirm calendar item identity

**Files:**
- Modify: `frontend/src/shared/api.ts`
- Read first: `backend/src/fitmas/legacy/app/api/app_views.py` (the calendar builder)
- Modify (if needed): `frontend/src/types.ts`

- [ ] **Step 1: Confirm how a calendar day item maps to an activity id**

Read `app_views.py` `build_app_calendar` (and the `CalendarItem` shape in `types.ts`). Confirm: for an off-plan activity item (`kind === "offplan"`), `item.id` is the **activity id**; for a planned session (`kind === "session"`, `status === "planned"`), `item.id` is the **session id**. If the off-plan item does NOT carry the activity id, add an `activity_id` field to the calendar item (builder + `types.ts`) so the UI can call the link endpoint. Note the finding inline in this task before coding the UI.

- [ ] **Step 2: Add the API client functions**

In `frontend/src/shared/api.ts`:
```ts
export function linkActivityToSession(activityId: number, sessionId: number) {
  return fetchJson<{ activity_id: number; session_id: number | null; session_status: string | null }>(
    `/api/v0/activities/${activityId}/link`,
    { method: "POST", body: JSON.stringify({ session_id: sessionId }) },
  );
}

export function unlinkActivity(activityId: number) {
  return fetchJson<{ activity_id: number; session_id: number | null; session_status: string | null }>(
    `/api/v0/activities/${activityId}/unlink`,
    { method: "POST", body: JSON.stringify({}) },
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/shared/api.ts frontend/src/types.ts backend/src/fitmas/legacy/app/api/app_views.py
git commit -m "feat(webapp): calendar item carries activity id + link/unlink API client"
```

---

### Task 7: Day-panel link/unlink affordance

**Files:**
- Modify: `frontend/src/features/calendar/CalendarPage.tsx`

- [ ] **Step 1: Add the link control to the day panel**

In `CalendarPage`, within the day-panel column (the `selectedDay.items` map), for an **off-plan activity** item that is **not yet linked**, render a small "Lier à une séance" control listing the day's `planned` session items (`selectedDay.items.filter(i => i.kind === "session" && i.status === "planned")`). On selection, call `linkActivityToSession(activityId, sessionId)` then reload the calendar (re-run `loadCalendar(data.month.key)` and update state, or `navigate(0)` / revalidate the loader). For a **linked** activity, render a "Délier" button calling `unlinkActivity(activityId)` then reload. Use the existing `STATUS_STYLES`/button styling for visual consistency; respect the `<frontend_aesthetics>` doctrine (no generic look).

Keep the network call + reload in a small handler inside `CalendarPage` (e.g. `onLink(activityId, sessionId)`), not inside the presentational `DayEntry`.

- [ ] **Step 2: Verify the calendar still renders + the control appears**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: builds clean.

- [ ] **Step 3: Manual app verification (couche app)**

Start the API in v0 mode + the front, open the calendar, pick a day with an off-plan run and a planned session, link them → the session shows **fait**; délier → back to **prévu**. Confirm the linked state survives a reload (persisted in V0). Bonus: message the Telegram coach — it should see the session `done` at the next turn (snapshot reads `v0_scheduled_sessions.status`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/calendar/CalendarPage.tsx
git commit -m "feat(webapp): link/unlink an activity to a session from the calendar day panel"
```

---

## Self-review notes

- **Spec coverage:** schema (T1) · executor commands + audit + ownership (T2) · adapter (T3) · v0_source surfacing + user resolver (T4) · endpoints + v0-mode guard + register (T5) · API client + item identity (T6) · calendar UI + unlink (T7). All spec sections covered.
- **Out of scope (per spec):** legacy `/complete` `/skip` `/move` left untouched; chat/LLM matching deferred.
- **Type consistency:** `LinkActivityToSessionCommand(activity_id, session_id, evidence)` / `UnlinkActivityCommand(activity_id, evidence)` used identically in policy.py, executor.py, app_actions.py. `LinkResult{activity_id, session_id, session_status}` matches the API-client return type.
- **Known investigation:** T6 Step 1 confirms the off-plan calendar item carries the activity id; if not, the builder gains an `activity_id` field. This is an explicit step, not a placeholder.
