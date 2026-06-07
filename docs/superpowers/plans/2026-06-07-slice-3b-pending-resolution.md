# Slice 3b — Pending Resolution + Week Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the V0 confirmation loop — a proposed pending can be confirmed/declined by the user via an LLM-emitted `pending_resolution`; on accept of a `week_proposal` the verified week commits to a typed store and chains forward.

**Architecture:** General LLM-first resolution (the LLM interprets oui/non in context, emits a structured `pending_resolution`; the policy grounds the id and authorizes; the executor loads the stored payload and dispatches the commit by type). First commit handler = the typed week → new `v0_planned_weeks` table. Forward chaining: `propose_week` seeds from the last committed week, falling back to the LLM-declared seed at cold-start. Materialization into the executable plan (`v0_scheduled_sessions`) and the plan_patch commit handler are deliberately deferred.

**Tech Stack:** Python 3, sqlite3 (stdlib), pytest. Pure `runtime_v0` core (no `fitmas.decision/domain/llm/...` imports). Spec: `docs/superpowers/specs/2026-06-07-slice-3b-pending-resolution-design.md`.

---

## File Structure

Core files touched (all under `backend/src/fitmas/runtime_v0/`):

- `db.py` — **add** table `v0_planned_weeks` + register in `V0_TABLES`.
- `proposals.py` — **add** type `"pending_resolution"`, `PendingResolutionDraft`, field + (de)serialization.
- `tools_proposal.py` — **add** `resolve_pending` tool function.
- `tool_catalog.py` — **add** `resolve_pending` schema, exposed only when a pending is open.
- `policy.py` — **add** `ResolvePendingConfirmationCommand` + `_pending_resolution` branch; **change** `week_proposal` branch `answer_only` → `create_pending`.
- `executor.py` — **add** `_apply_resolve_pending` + `_apply_commit_week` + dispatch + `_target`.
- `snapshot.py` — **add** `WorldSnapshot.last_planned_week` field + `_load_last_planned_week`.
- `meso/runtime_tool.py` — **change** `propose_week` to prefer `snapshot.last_planned_week` (forward chaining).
- `reply.py` / `guard.py` — **add** a `pending_resolution` fallback branch (honest accept/reject text).

Tests touched (under `tests/runtime_v0/`): `test_db.py`, `test_propose_week.py`, `test_tools_proposal.py`, `test_tool_catalog.py`, `test_policy_rules.py`, `test_executor.py`, `test_snapshot.py`, `test_result_reply.py`, `test_runtime_flow.py`, `test_import_boundaries.py`.

Script (couche 2, run manually): `scripts/v0_eval/probe_resolve_pending.py`.

Run the full suite at any time with: `.venv/bin/python -m pytest tests/runtime_v0 -q`.

---

## Task 1: Typed week store table

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/db.py`
- Test: `tests/runtime_v0/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_db.py`:

```python
def test_planned_weeks_table_exists_and_resets(tmp_path):
    from fitmas.runtime_v0.db import connect, init_db, reset_db

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-15", "llm", 350.0, "threshold", "[]"),
        )
        connection.commit()
        row = connection.execute("select * from v0_planned_weeks").fetchone()
    assert row["status"] == "committed"
    assert row["week_start"] == "2026-06-15"

    reset_db(db_path)
    with connect(db_path) as connection:
        count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_db.py::test_planned_weeks_table_exists_and_resets -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: v0_planned_weeks`.

- [ ] **Step 3: Add the table to the schema**

In `db.py`, inside the `SCHEMA` string, add this block right after the `v0_scheduled_sessions` table (before `v0_activities`):

```sql
CREATE TABLE IF NOT EXISTS v0_planned_weeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    source TEXT NOT NULL,
    week_load REAL NOT NULL,
    key_type TEXT NOT NULL,
    sessions_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'committed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 4: Register the table for reset**

In `db.py`, add `"v0_planned_weeks",` to the `V0_TABLES` tuple (order is drop-order; put it near the top with the other leaf tables):

```python
V0_TABLES = (
    "v0_idempotency_locks",
    "v0_pending_confirmations",
    "v0_conversation_state",
    "v0_planned_weeks",
    "v0_facts",
    "v0_activities",
    "v0_scheduled_sessions",
    "v0_command_events",
    "v0_turns",
    "v0_input_events",
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/db.py tests/runtime_v0/test_db.py
git commit -m "feat(meso): add v0_planned_weeks typed store table

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `pending_resolution` proposal type + draft

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/proposals.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_propose_week.py`:

```python
def test_pending_resolution_roundtrips():
    from fitmas.runtime_v0.proposals import PendingResolutionDraft

    proposal = ActionProposal(
        type="pending_resolution",
        confidence=1.0,
        user_intent_summary="resolve pending",
        evidence=(),
        pending_resolution=PendingResolutionDraft(pending_id=7, decision="accept", note="ok"),
    )
    restored = proposal_from_dict(proposal_to_dict(proposal))
    assert restored.type == "pending_resolution"
    assert restored.pending_resolution == PendingResolutionDraft(pending_id=7, decision="accept", note="ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py::test_pending_resolution_roundtrips -v`
Expected: FAIL with `ImportError: cannot import name 'PendingResolutionDraft'`.

- [ ] **Step 3: Add the draft + type + field**

In `proposals.py`, add the dataclass after `WeekProposalDraft`:

```python
@dataclass(frozen=True)
class PendingResolutionDraft:
    pending_id: int
    decision: Literal["accept", "reject"]
    note: str = ""
```

In the `ActionProposal.type` `Literal[...]`, add `"pending_resolution",` (next to `"week_proposal"`).

In `ActionProposal`, add the field after `week_proposal`:

```python
    pending_resolution: PendingResolutionDraft | None = None
```

- [ ] **Step 4: Wire (de)serialization**

In `proposal_from_dict`, after the `week_proposal = data.get("week_proposal")` line add:

```python
    pending_resolution = data.get("pending_resolution")
```

and in the returned `ActionProposal(...)`, after the `week_proposal=...` argument add:

```python
        pending_resolution=(
            PendingResolutionDraft(
                pending_id=pending_resolution["pending_id"],
                decision=pending_resolution["decision"],
                note=pending_resolution.get("note", ""),
            )
            if pending_resolution is not None
            else None
        ),
```

(`proposal_to_dict` needs no change — `_jsonable` already serializes the dataclass via `asdict`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py::test_pending_resolution_roundtrips -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/proposals.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(runtime): add pending_resolution proposal type + draft

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `resolve_pending` tool

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/tools_proposal.py`
- Test: `tests/runtime_v0/test_tools_proposal.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_tools_proposal.py` (mirror the existing helper that builds a `ToolContext` in that file; if none, construct one inline as below):

```python
def test_resolve_pending_builds_pending_resolution_proposal():
    from fitmas.runtime_v0.tools_proposal import resolve_pending
    from fitmas.runtime_v0.tools_read import ToolContext

    ctx = ToolContext(db_path=None, snapshot=None, scratchpad={})
    proposal = resolve_pending(ctx, pending_id=7, decision="reject", note="pas cette semaine")
    assert proposal.type == "pending_resolution"
    assert proposal.pending_resolution.pending_id == 7
    assert proposal.pending_resolution.decision == "reject"
    assert proposal.pending_resolution.note == "pas cette semaine"
    assert proposal.tool_trace[-1]["name"] == "resolve_pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_tools_proposal.py::test_resolve_pending_builds_pending_resolution_proposal -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_pending'`.

- [ ] **Step 3: Implement the tool**

In `tools_proposal.py`, add `PendingResolutionDraft` to the import block from `proposals`, then add the function (next to `propose_fact_resolution`):

```python
def resolve_pending(
    ctx: ToolContext,
    pending_id: int,
    decision: str,
    note: str = "",
) -> ActionProposal:
    _record(ctx, "resolve_pending", True)
    return ActionProposal(
        type="pending_resolution",
        confidence=1.0,
        user_intent_summary="pending resolution",
        evidence=(note,) if note else (),
        tool_trace=_trace(ctx),
        pending_resolution=PendingResolutionDraft(
            pending_id=pending_id,
            decision=decision,
            note=note,
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_tools_proposal.py::test_resolve_pending_builds_pending_resolution_proposal -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/tools_proposal.py tests/runtime_v0/test_tools_proposal.py
git commit -m "feat(runtime): add resolve_pending coach-callable tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Catalog exposure gated on an open pending

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/tool_catalog.py`
- Test: `tests/runtime_v0/test_tool_catalog.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_tool_catalog.py` (reuse the file's existing `_snapshot`/event helpers; the snippet below builds them inline if needed):

```python
def test_resolve_pending_exposed_only_when_pending_open():
    from datetime import datetime, timezone
    from fitmas.runtime_v0.event import InputEvent
    from fitmas.runtime_v0.snapshot import PendingView, WorldSnapshot
    from fitmas.runtime_v0.state import ConversationState
    from fitmas.runtime_v0.tool_catalog import for_event

    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    base = dict(
        user_id=1, today=now.date(), now=now, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=(),
        recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )
    event = InputEvent(id="e1", user_id=1, source="test", type="user_message",
                       text="oui", payload={}, occurred_at=now)

    no_pending = WorldSnapshot(active_pending=None, **base)
    names = {tool.name for tool in for_event(event, no_pending)}
    assert "resolve_pending" not in names

    pending = PendingView(id=3, type="week_proposal", summary="semaine proposée", expires_at=now)
    with_pending = WorldSnapshot(active_pending=pending, **base)
    names = {tool.name for tool in for_event(event, with_pending)}
    assert "resolve_pending" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_tool_catalog.py::test_resolve_pending_exposed_only_when_pending_open -v`
Expected: FAIL (`resolve_pending` never in the set).

- [ ] **Step 3: Implement the gated exposure**

In `tool_catalog.py`, import `resolve_pending` in the `tools_proposal` import block. Then, inside `for_event`, after the `tools = ( ... )` tuple is built and **before** the `move_session` filtering block, insert:

```python
    if snapshot.active_pending is not None:
        tools = tools + (
            ToolSchema(
                name="resolve_pending",
                description=(
                    "Resolve the open pending confirmation shown in the header. "
                    "Use when the user accepts or declines it. decision=accept commits "
                    "it; decision=reject drops it. Pass the pending id from the header."
                ),
                parameters=_schema(
                    {
                        "pending_id": {"type": "integer"},
                        "decision": {"type": "string", "enum": ["accept", "reject"]},
                        "note": {"type": "string"},
                    },
                    ("pending_id", "decision"),
                ),
                handler=resolve_pending,
                is_proposal=True,
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_tool_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/tool_catalog.py tests/runtime_v0/test_tool_catalog.py
git commit -m "feat(runtime): expose resolve_pending only when a pending is open

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Policy — `ResolvePendingConfirmationCommand` + `_pending_resolution` branch

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/policy.py`
- Test: `tests/runtime_v0/test_policy_rules.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_policy_rules.py`:

```python
def test_pending_resolution_grounds_against_open_pending():
    from datetime import datetime, timezone
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand, RuntimePolicy
    from fitmas.runtime_v0.proposals import ActionProposal, PendingResolutionDraft
    from fitmas.runtime_v0.snapshot import PendingView, WorldSnapshot
    from fitmas.runtime_v0.state import ConversationState

    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    base = dict(
        user_id=1, today=now.date(), now=now, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=(),
        recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )
    pending = PendingView(id=5, type="week_proposal", summary="semaine du 8 juin", expires_at=now)
    snapshot = WorldSnapshot(active_pending=pending, **base)

    def _proposal(pid, decision):
        return ActionProposal(
            type="pending_resolution", confidence=1.0, user_intent_summary="r",
            evidence=(), pending_resolution=PendingResolutionDraft(pending_id=pid, decision=decision),
        )

    # wrong id -> clarification, no command
    wrong = RuntimePolicy().evaluate(_proposal(99, "accept"), snapshot)
    assert wrong.action == "ask_clarification"
    assert wrong.commands == ()

    # accept -> allow_commit + resolve command, reply carries the week summary
    accept = RuntimePolicy().evaluate(_proposal(5, "accept"), snapshot)
    assert accept.action == "allow_commit"
    assert accept.commands == (ResolvePendingConfirmationCommand(pending_id=5, decision="accept", note=""),)
    assert "semaine du 8 juin" in accept.reply_facts[0]

    # reject -> allow_commit + resolve command
    reject = RuntimePolicy().evaluate(_proposal(5, "reject"), snapshot)
    assert reject.action == "allow_commit"
    assert reject.commands == (ResolvePendingConfirmationCommand(pending_id=5, decision="reject", note=""),)

    # no open pending -> clarification
    no_pending = WorldSnapshot(active_pending=None, **base)
    none = RuntimePolicy().evaluate(_proposal(5, "accept"), no_pending)
    assert none.action == "ask_clarification"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_policy_rules.py::test_pending_resolution_grounds_against_open_pending -v`
Expected: FAIL with `ImportError: cannot import name 'ResolvePendingConfirmationCommand'`.

- [ ] **Step 3: Add the command dataclass**

In `policy.py`, add after `ResolveMemoryFactCommand`:

```python
@dataclass(frozen=True)
class ResolvePendingConfirmationCommand(Command):
    pending_id: int
    decision: Literal["accept", "reject"]
    note: str
```

- [ ] **Step 4: Add the policy branch**

In `RuntimePolicy._evaluate_type`, add a branch in the `elif` chain (after the `fact_resolution` branch):

```python
        elif proposal.type == "pending_resolution":
            decision = self._pending_resolution(proposal, snapshot)
```

Then add the method to `RuntimePolicy` (next to `_fact_resolution`):

```python
    def _pending_resolution(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        draft = proposal.pending_resolution
        if draft is None:
            return _decision("block", "missing_pending_resolution", "low", (), ())
        pending = snapshot.active_pending
        # Ground the LLM-supplied id against the open pending before committing.
        if pending is None or draft.pending_id != pending.id:
            return _decision("ask_clarification", "pending_not_active", "low", (), ("De quelle proposition tu parles ?",))
        command = ResolvePendingConfirmationCommand(
            pending_id=pending.id, decision=draft.decision, note=draft.note
        )
        if draft.decision == "reject":
            return _decision("allow_commit", "pending_rejected", "low", (command,), (f"annulé : {pending.summary}",))
        return _decision("allow_commit", "pending_accepted", "low", (command,), (pending.summary,))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_policy_rules.py::test_pending_resolution_grounds_against_open_pending -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/policy.py tests/runtime_v0/test_policy_rules.py
git commit -m "feat(runtime): policy grounds + authorizes pending_resolution

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Policy — `week_proposal` becomes a pending

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/policy.py:116-120`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Update the existing failing test**

In `tests/runtime_v0/test_propose_week.py`, replace `test_policy_shows_week_proposal_without_commit` with:

```python
def test_policy_routes_week_proposal_to_pending():
    from fitmas.runtime_v0.policy import CreatePendingConfirmationCommand
    from fitmas.runtime_v0.proposals import proposal_from_dict
    import json

    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    decision = RuntimePolicy().evaluate(proposal, _snapshot())

    assert decision.action == "create_pending"
    assert len(decision.commands) == 1
    command = decision.commands[0]
    assert isinstance(command, CreatePendingConfirmationCommand)
    assert command.type == "week_proposal"
    # the full verified week rides in the payload for the commit handler
    restored = proposal_from_dict(json.loads(command.payload_json))
    assert restored.week_proposal.sessions[0]["type"] == "threshold"
    # the reply still shows the proposed week
    assert decision.reply_facts == proposal.answer_facts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py::test_policy_routes_week_proposal_to_pending -v`
Expected: FAIL — current branch returns `answer_only` with no commands.

- [ ] **Step 3: Change the policy branch**

In `policy.py`, replace the `week_proposal` block in `_evaluate_type` (currently the `answer_only` branch with the 3a comment) with:

```python
        if proposal.type == "week_proposal":
            draft = proposal.week_proposal
            if draft is None:
                return _decision("block", "missing_week_proposal", "low", (), ())
            summary = proposal.answer_facts[0] if proposal.answer_facts else f"semaine proposée du {draft.week_start}"
            pending = CreatePendingConfirmationCommand(
                type="week_proposal",
                summary=summary,
                payload_json=json.dumps(proposal_to_dict(proposal), ensure_ascii=False, sort_keys=True),
                expires_at=snapshot.now + timedelta(hours=24),
            )
            return _decision("create_pending", "week_proposal", "low", (pending,), proposal.answer_facts)
```

(`json`, `timedelta`, `CreatePendingConfirmationCommand`, `proposal_to_dict` are already imported in `policy.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v`
Expected: PASS (the new test passes; the tool-level tests are unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/policy.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): route week_proposal to pending (was answer_only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Executor — commit week on accept, drop on reject

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/executor.py`
- Test: `tests/runtime_v0/test_executor.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/runtime_v0/test_executor.py` (the `_db` helper and imports already exist in that file):

```python
def _open_week_pending(db_path, pending_id=1, ptype="week_proposal"):
    payload = {
        "type": "week_proposal",
        "week_proposal": {
            "week_start": "2026-06-15",
            "source": "llm",
            "week_load": 350.0,
            "key_type": "threshold",
            "sessions": [
                {"date": "2026-06-16", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": "3x8"},
            ],
        },
    }
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations (id, user_id, type, summary, payload_json, status, expires_at) "
            "values (?, ?, ?, ?, ?, 'open', ?)",
            (pending_id, 1, ptype, "semaine du 15 juin", json.dumps(payload), "2026-06-30T00:00:00+00:00"),
        )
        connection.commit()


def test_resolve_pending_accept_commits_week(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1)

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="accept", note=""),),
        turn_id="turn-accept",
    )

    with connect(db_path) as connection:
        week = connection.execute("select * from v0_planned_weeks").fetchone()
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "applied"
    assert week["week_start"] == "2026-06-15"
    assert week["key_type"] == "threshold"
    assert json.loads(week["sessions_json"])[0]["type"] == "threshold"
    assert pending["status"] == "accepted"


def test_resolve_pending_reject_drops_without_store_write(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1)

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="reject", note="pas cette semaine"),),
        turn_id="turn-reject",
    )

    with connect(db_path) as connection:
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "applied"
    assert week_count == 0
    assert pending["status"] == "rejected"


def test_resolve_pending_accept_unsupported_type_fails_loud(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1, ptype="plan_patch")

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="accept", note=""),),
        turn_id="turn-bad",
    )

    with connect(db_path) as connection:
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "blocked"
    assert "pending_commit_not_supported_for_type" in events[0].reason
    assert pending["status"] == "open"  # rolled back, not lost
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor.py -k resolve_pending -v`
Expected: FAIL with `ImportError: cannot import name 'ResolvePendingConfirmationCommand'` then, once importable, `unsupported_command`.

- [ ] **Step 3: Implement the executor handlers**

In `executor.py`, add `ResolvePendingConfirmationCommand` to the import block from `policy`. Then add a dispatch line in `_apply_command` (before the final `raise ValueError("unsupported_command")`):

```python
    if isinstance(command, ResolvePendingConfirmationCommand):
        return _apply_resolve_pending(command, connection, user_id)
```

Add the two handlers (next to `_apply_resolve_memory_fact`):

```python
def _apply_resolve_pending(command: ResolvePendingConfirmationCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    row = connection.execute(
        "select * from v0_pending_confirmations where id = ? and user_id = ? and status = 'open'",
        (command.pending_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("pending_not_open")
    before = dict(row)
    if command.decision == "reject":
        connection.execute(
            "update v0_pending_confirmations set status = 'rejected' where id = ?", (command.pending_id,)
        )
        after = _pending(connection, command.pending_id)
        return before, after, command.note or "rejected"
    payload = json.loads(before["payload_json"])
    if before["type"] == "week_proposal":
        after = _apply_commit_week(payload, connection, user_id)
    else:
        raise ValueError(f"pending_commit_not_supported_for_type:{before['type']}")
    connection.execute(
        "update v0_pending_confirmations set status = 'accepted' where id = ?", (command.pending_id,)
    )
    return before, after, command.note or "accepted"


def _apply_commit_week(payload: dict[str, Any], connection, user_id: int) -> dict[str, Any]:
    week = payload.get("week_proposal")
    if not week:
        raise ValueError("pending_week_payload_missing")
    cursor = connection.execute(
        "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
        "values (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            week["week_start"],
            week["source"],
            week["week_load"],
            week["key_type"],
            json.dumps(week["sessions"], ensure_ascii=False),
        ),
    )
    row = connection.execute("select * from v0_planned_weeks where id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)
```

Add a `_target` mapping (in `_target`, before the final `return "unknown", ...`):

```python
    if isinstance(command, ResolvePendingConfirmationCommand):
        return "pending", str(command.pending_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor.py -v`
Expected: PASS (new resolve tests + all existing executor tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/executor.py tests/runtime_v0/test_executor.py
git commit -m "feat(meso): executor commits a confirmed week / drops on reject

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Snapshot loads the last committed week + forward chaining

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/snapshot.py`, `backend/src/fitmas/runtime_v0/meso/runtime_tool.py`
- Test: `tests/runtime_v0/test_snapshot.py`, `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing snapshot test**

Add to `tests/runtime_v0/test_snapshot.py` (this file already builds a db; reuse its db helper, or use `init_db`/`connect` directly as below):

```python
def test_snapshot_loads_last_committed_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.meso.model import WeekActuals
    from fitmas.runtime_v0.snapshot import SnapshotBuilder

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-01", "llm", 300.0, "threshold", "[]"),
        )
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-08", "llm", 330.0, "intervals", "[]"),
        )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(1, datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc))
    assert snapshot.last_planned_week == WeekActuals(total_load=330.0, key_type="intervals")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py::test_snapshot_loads_last_committed_week -v`
Expected: FAIL (`WorldSnapshot` has no attribute `last_planned_week`).

- [ ] **Step 3: Add the field + loader to the snapshot**

In `snapshot.py`, add the import near the top:

```python
from fitmas.runtime_v0.meso.model import WeekActuals
```

Add the field to `WorldSnapshot` (as the last field, with a default so existing constructors keep working):

```python
    last_planned_week: WeekActuals | None = None
```

In `SnapshotBuilder.build`, inside the `with connect(...)` block add:

```python
            last_planned_week = _load_last_planned_week(connection, user_id)
```

and pass it in the returned `WorldSnapshot(...)`:

```python
            last_planned_week=last_planned_week,
```

Add the loader (next to `_load_pending`):

```python
def _load_last_planned_week(connection, user_id: int) -> WeekActuals | None:
    row = connection.execute(
        "select week_load, key_type from v0_planned_weeks "
        "where user_id = ? and status = 'committed' order by week_start desc, id desc limit 1",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return WeekActuals(total_load=row["week_load"], key_type=row["key_type"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing chaining test**

Add to `tests/runtime_v0/test_propose_week.py`:

```python
def test_propose_week_chains_from_last_committed_week():
    from fitmas.runtime_v0.meso.model import WeekActuals

    # snapshot carries a committed prior week at load 400, key intervals.
    chained = WorldSnapshot(
        user_id=1, today=NOW.date(), now=NOW, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=(),
        active_pending=None, recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
        last_planned_week=WeekActuals(total_load=400.0, key_type="intervals"),
    )
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=chained, generation_llm=generation_llm)
    # declared seed is deliberately different; chaining must win.
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    assert proposal.week_proposal.band == (400.0, 440.0)  # build 100->110% of 400
    assert proposal.week_proposal.key_type == "intervals"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py::test_propose_week_chains_from_last_committed_week -v`
Expected: FAIL — band is `(300.0, 330.0)` (still using the declared seed).

- [ ] **Step 7: Implement forward chaining in `propose_week`**

In `meso/runtime_tool.py`, replace the seed/target lines in `propose_week`:

```python
    snapshot = ctx.snapshot
    actuals = WeekActuals(total_load=float(last_week_load), key_type=key_type)
    target = derive_continuity_target(actuals, phase)
```

with:

```python
    snapshot = ctx.snapshot
    # Forward chaining: a committed prior week is the seed of record; the
    # LLM-declared seed is the cold-start fallback (no committed week yet).
    actuals = snapshot.last_planned_week or WeekActuals(
        total_load=float(last_week_load), key_type=key_type
    )
    target = derive_continuity_target(actuals, phase)
```

Then, further down, change the `draft = WeekProposalDraft(... key_type=key_type ...)` argument to `key_type=actuals.key_type`, and in the `facts` headline change the trailing `clé {key_type})` interpolation and the f-string variable to use `actuals.key_type`:

```python
    draft = WeekProposalDraft(
        week_start=week_start.isoformat(),
        source=result.source,
        week_load=result.week.week_load,
        band=target.load_band,
        key_type=actuals.key_type,
        sessions=sessions,
    )
    facts = (
        f"semaine proposée du {week_start.isoformat()} — charge {result.week.week_load} "
        f"(cible {target.load_band[0]}-{target.load_band[1]}, clé {actuals.key_type})",
    ) + tuple(
        f"{s['date']} {s['type']} {s['duration_min']}min {s['intensity']}" for s in sessions
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v`
Expected: PASS (chaining test passes; the cold-start tests still pass because `last_planned_week` defaults to `None`).

- [ ] **Step 9: Commit**

```bash
git add backend/src/fitmas/runtime_v0/snapshot.py backend/src/fitmas/runtime_v0/meso/runtime_tool.py tests/runtime_v0/test_snapshot.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): chain propose_week forward from the last committed week

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Reply + guard fallback for `pending_resolution`

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/reply.py`, `backend/src/fitmas/runtime_v0/guard.py`
- Test: `tests/runtime_v0/test_result_reply.py`

The happy path already works: `result.read_facts = policy.reply_facts` (the week summary on accept, the cancellation line on reject), so the reply LLM composes from it and the guard's CLAIM check is satisfied by the applied resolve event. These two small additions make the **deterministic fallbacks** honest if the reply LLM is unavailable or its output gets blocked.

- [ ] **Step 1: Write the failing test**

Add to `tests/runtime_v0/test_result_reply.py` (reuse the module's `RuntimeResult`/`CommandEvent` construction helpers; the inline build below is self-contained):

```python
def test_pending_resolution_fallback_uses_read_facts():
    from datetime import date
    from fitmas.runtime_v0.guard import _safe_reply
    from fitmas.runtime_v0.reply import _fallback
    from fitmas.runtime_v0.result import ReplyContract, RuntimeResult

    result = RuntimeResult(
        event_id="e1", turn_id="t1", proposal_type="pending_resolution",
        policy_action="allow_commit", committed_events=(), blocked_reasons=(),
        pending=None, read_facts=("semaine du 8 juin validée",),
        reply_contract=ReplyContract((), (), "confirming", 5),
    )
    assert _fallback(result, _snapshot_for_reply()) == "semaine du 8 juin validée"
    assert _safe_reply(result, date(2026, 6, 4)) == "semaine du 8 juin validée"
```

If `test_result_reply.py` has no `_snapshot_for_reply` helper, add this minimal one to the file:

```python
def _snapshot_for_reply():
    from datetime import datetime, timezone
    from fitmas.runtime_v0.snapshot import WorldSnapshot
    from fitmas.runtime_v0.state import ConversationState
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    return WorldSnapshot(
        user_id=1, today=now.date(), now=now, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=(),
        active_pending=None, recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_result_reply.py::test_pending_resolution_fallback_uses_read_facts -v`
Expected: FAIL — `_fallback` returns `TECHNICAL_FALLBACK` for an `allow_commit` turn with no summarizable event.

- [ ] **Step 3: Add the reply fallback branch**

In `reply.py`, in `_fallback`, add this branch immediately before `return TECHNICAL_FALLBACK`:

```python
    if result.proposal_type == "pending_resolution" and result.read_facts:
        return result.read_facts[0]
```

- [ ] **Step 4: Add the guard sanitized-fallback branch**

In `guard.py`, in `_safe_reply`, add this branch immediately before `return TECHNICAL_FALLBACK`:

```python
    if result.proposal_type == "pending_resolution" and result.read_facts:
        return result.read_facts[0]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_result_reply.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/reply.py backend/src/fitmas/runtime_v0/guard.py tests/runtime_v0/test_result_reply.py
git commit -m "feat(runtime): honest deterministic fallback for pending_resolution

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: End-to-end — propose → confirm → commit (+ reject)

**Files:**
- Test: `tests/runtime_v0/test_runtime_flow.py`

This exercises the whole loop across two turns with fake LLMs: turn 1 proposes (creates the pending), turn 2 resolves it (commits the week / drops it).

- [ ] **Step 1: Write the failing end-to-end test**

Add to `tests/runtime_v0/test_runtime_flow.py` (reuse the module's existing imports; the snippet imports what it needs):

```python
def test_propose_then_confirm_commits_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.event import InputEvent
    from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
    from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
    from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # Thursday
    good_week = [
        {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},
        {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},
        {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},
        {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"},
    ]
    coach = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
        LLMResponse(tool_calls=(ToolCall(name="resolve_pending", args={"pending_id": 1, "decision": "accept"}),)),
    ])
    generation = FakeLLMClient([LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": good_week}),))])
    reply = FakeLLMClient([
        LLMResponse(text="Voici ta semaine du 8 juin, je cale ?"),
        LLMResponse(text="C'est calé, ta semaine du 8 juin est validée."),
    ])
    deps = RuntimeDeps(db_path=db_path, coach_llm=coach, reply_llm=reply, generation_llm=generation)

    e1 = InputEvent(id="e1", user_id=1, source="test", type="user_message", text="fais-moi ma semaine prochaine", payload={}, occurred_at=now)
    r1 = handle_event(e1, deps, turn_id="turn-1")
    assert r1.policy.action == "create_pending"
    with connect(db_path) as connection:
        pending = connection.execute("select id, status from v0_pending_confirmations").fetchone()
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
    assert pending["status"] == "open"
    assert week_count == 0  # nothing committed yet

    e2 = InputEvent(id="e2", user_id=1, source="test", type="user_message", text="oui", payload={}, occurred_at=now)
    r2 = handle_event(e2, deps, turn_id="turn-2")
    assert r2.policy.action == "allow_commit"
    with connect(db_path) as connection:
        week = connection.execute("select * from v0_planned_weeks").fetchone()
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert week["week_start"] == "2026-06-08"
    assert week["key_type"] == "threshold"
    assert pending["status"] == "accepted"
    assert r2.guard.ok


def test_propose_then_reject_drops_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.event import InputEvent
    from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
    from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
    from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    good_week = [
        {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},
        {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},
        {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},
        {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"},
    ]
    coach = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
        LLMResponse(tool_calls=(ToolCall(name="resolve_pending", args={"pending_id": 1, "decision": "reject"}),)),
    ])
    generation = FakeLLMClient([LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": good_week}),))])
    reply = FakeLLMClient([
        LLMResponse(text="Voici ta semaine du 8 juin, je cale ?"),
        LLMResponse(text="Ok, je laisse tomber cette semaine."),
    ])
    deps = RuntimeDeps(db_path=db_path, coach_llm=coach, reply_llm=reply, generation_llm=generation)

    handle_event(InputEvent(id="e1", user_id=1, source="test", type="user_message", text="fais-moi ma semaine", payload={}, occurred_at=now), deps, turn_id="turn-1")
    r2 = handle_event(InputEvent(id="e2", user_id=1, source="test", type="user_message", text="non", payload={}, occurred_at=now), deps, turn_id="turn-2")

    with connect(db_path) as connection:
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert week_count == 0
    assert pending["status"] == "rejected"
    assert r2.guard.ok
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_runtime_flow.py -k "propose_then" -v`
Expected: PASS. (All implementation already exists from Tasks 1-9; this is the integration proof. If a test fails, fix the offending task before continuing — do not weaken the assertion.)

- [ ] **Step 3: Run the whole core suite**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q`
Expected: PASS (all green).

- [ ] **Step 4: Commit**

```bash
git add tests/runtime_v0/test_runtime_flow.py
git commit -m "test(meso): end-to-end propose -> confirm/reject -> commit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Couche-2 probe (real provider, run manually)

**Files:**
- Create: `scripts/v0_eval/probe_resolve_pending.py`

This is the **real proof bar** (couche 2): an unscripted two-turn exchange driven by a real provider (DeepSeek). It is not part of `pytest`; it runs manually and needs `ANTHROPIC_API_KEY`/provider creds. Mirror `scripts/v0_eval/probe_propose_week.py` for the provider/client wiring and the turn-driving helpers.

- [ ] **Step 1: Read the sibling probe to copy its scaffolding**

Run: `sed -n '1,80p' scripts/v0_eval/probe_propose_week.py`
Note how it builds the providers, the `RuntimeDeps` (including `generation_llm` at the 4096 token budget), seeds the DB, and drives a turn via `handle_event`.

- [ ] **Step 2: Write the probe**

Create `scripts/v0_eval/probe_resolve_pending.py` following that scaffolding, with this flow (reuse the helper functions from `probe_propose_week.py` — import them or copy the seeding/turn helpers verbatim, matching the existing file's style):

```python
"""Couche-2 probe: propose a week, then confirm it in a second unscripted turn.

Proves Slice 3b end to end on a real provider: turn 1 the coach proposes a week
(pending), turn 2 the user accepts in natural language and the verified week
commits to v0_planned_weeks with an honest reply. A mirror run with a refusal
("non, pas cette semaine") must drop the pending and write nothing.

Run: python3 scripts/v0_eval/probe_resolve_pending.py [--provider deepseek]
Not a pytest test (needs provider creds); this is the couche-2 proof bar.
"""
from __future__ import annotations

# Reuse probe_propose_week's provider/deps/seed helpers (same directory).
from probe_propose_week import (  # type: ignore
    build_deps,          # -> RuntimeDeps with coach/reply/generation clients
    parse_provider_arg,  # -> provider name from argv
    seed_recent_training,  # seeds a realistic last real week into the DB
    fresh_db,            # -> a temp v0 DB path
)

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.runtime import handle_event
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)


def _event(eid: str, text: str) -> InputEvent:
    return InputEvent(id=eid, user_id=1, source="probe", type="user_message", text=text, payload={}, occurred_at=_now())


def run(provider: str, second_turn_text: str, expect_commit: bool) -> None:
    db_path = fresh_db()
    seed_recent_training(db_path)
    deps = build_deps(db_path, provider)

    r1 = handle_event(_event("p1", "fais-moi ma semaine prochaine"), deps, turn_id="probe-1")
    print(f"[turn 1] action={r1.policy.action} reply={r1.reply!r}")

    r2 = handle_event(_event("p2", second_turn_text), deps, turn_id="probe-2")
    print(f"[turn 2] action={r2.policy.action} reply={r2.reply!r} guard_ok={r2.guard.ok}")

    with connect(db_path) as connection:
        weeks = connection.execute("select week_start, key_type, week_load from v0_planned_weeks").fetchall()
        pending = connection.execute("select status from v0_pending_confirmations order by id desc limit 1").fetchone()
    committed = [dict(w) for w in weeks]
    print(f"committed_weeks={committed} pending_status={pending['status'] if pending else None}")

    ok = (len(committed) == 1) if expect_commit else (len(committed) == 0)
    print("RESULT:", "PASS" if ok and r2.guard.ok else "FAIL")


if __name__ == "__main__":
    provider = parse_provider_arg()
    print("=== accept path ===")
    run(provider, "oui c'est parfait, on part là-dessus", expect_commit=True)
    print("=== reject path ===")
    run(provider, "non, pas cette semaine en fait", expect_commit=False)
```

> If `probe_propose_week.py` does not expose `build_deps`/`parse_provider_arg`/`seed_recent_training`/`fresh_db` under those names, copy the equivalent inline helpers from it (matching its actual function names) rather than importing — keep this probe self-contained and runnable.

- [ ] **Step 3: Run the probe (manual, needs creds)**

Run: `python3 scripts/v0_eval/probe_resolve_pending.py --provider deepseek`
Expected: `accept path` prints `RESULT: PASS` (one committed week, honest reply, guard ok); `reject path` prints `RESULT: PASS` (zero committed weeks, pending rejected). Capture the output for the BUILD-ORDER advancement note.

- [ ] **Step 4: Commit**

```bash
git add scripts/v0_eval/probe_resolve_pending.py
git commit -m "test(meso): couche-2 probe for propose -> confirm -> commit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Bump the cap + update docs (landing)

**Files:**
- Modify: `tests/runtime_v0/test_import_boundaries.py`, `docs/RUNTIME-V0.md`, `docs/BUILD-ORDER.md`

- [ ] **Step 1: Measure the real core LOC**

Run: `.venv/bin/python -c "from pathlib import Path; root=Path('backend/src/fitmas/runtime_v0'); print(sum(len(p.read_text().splitlines()) for p in root.rglob('*.py') if '__pycache__' not in p.parts and 'adapters' not in p.parts and ' 2' not in p.name))"`
Note the printed number (call it `N`).

- [ ] **Step 2: Update the cap to the measured value**

In `tests/runtime_v0/test_import_boundaries.py`, append a history line in the comment block and set the assertion to `N` rounded up to the next ten (headroom), e.g. if `N == 4243` use `4250`:

```python
    # 4100 -> <ROUNDED_N> (7 juin 2026): Slice 3b — pending_resolution mechanism,
    # resolve_pending tool, v0_planned_weeks store, week commit handler, forward
    # chaining. Proven capability, not creep (see RUNTIME-V0.md Budget).
    loc = sum(len(path.read_text().splitlines()) for path in _core_files())
    assert loc <= <ROUNDED_N>
```

- [ ] **Step 3: Run the boundary test**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_import_boundaries.py -v`
Expected: PASS (3 tests, including the cap).

- [ ] **Step 4: Update the docs**

In `docs/RUNTIME-V0.md` Budget section, update the measured number line to `~N LOC` and the cap to `<ROUNDED_N>`. In `docs/BUILD-ORDER.md`, in the meso advancement block, append a one-paragraph "Slice 3b codée" note (mechanism + store + chaining + couche-2 result from Task 11), and change the "Suite immédiate" line from Slice 3b to the next item (materialization / plan_patch commit handler — both deferred follow-ups). Update the "Etat Actuel" LOC line to `~N (cap <ROUNDED_N>)`.

- [ ] **Step 5: Commit**

```bash
git add tests/runtime_v0/test_import_boundaries.py docs/RUNTIME-V0.md docs/BUILD-ORDER.md
git commit -m "chore(meso): Slice 3b landed — cap bump + docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- General `pending_resolution` (LLM emits, policy grounds) → Tasks 2, 3, 4, 5. ✅
- Week commit → `v0_planned_weeks` (store typé) → Tasks 1, 7. ✅
- `week_proposal` → `create_pending` (was `answer_only`) → Task 6. ✅
- Forward chaining (`snapshot.last_planned_week` → `propose_week`) → Task 8. ✅
- accept/reject only; reject = no métier write → Tasks 5, 7. ✅
- Grounding / idempotency / honesty (reply+guard) → Tasks 5 (grounding), 7 (status filter = cross-turn idempotency), 9 (honest fallback). ✅
- Tests couche 1 + couche 2 → Tasks 1-10 (unit/integration) + 11 (probe). ✅
- Non-goals (materialization, plan_patch commit handler, re-verify, modify) → not implemented by design; plan_patch commit fails loud (Task 7). ✅
- Cap bump at landing → Task 12. ✅

**Placeholder scan:** the only intentionally non-literal values are `N`/`<ROUNDED_N>` in Task 12, which are measured at landing (Step 1 gives the exact command). The Task 11 probe notes the fallback if sibling helper names differ. No other TODO/TBD.

**Type consistency:** `PendingResolutionDraft(pending_id, decision, note="")` is defined in Task 2 and used identically in Tasks 3, 5. `ResolvePendingConfirmationCommand(pending_id, decision, note)` is defined in Task 5 and used identically in Tasks 6-test, 7. `WeekActuals(total_load=, key_type=)` matches the existing `meso/model.py` definition (used in Tasks 8). `v0_planned_weeks` columns (`week_start, source, week_load, key_type, sessions_json, status`) are identical across Tasks 1, 7, 8. `last_planned_week` field name is consistent across Tasks 8 (snapshot, runtime_tool, tests). ✅
