# Slice 3a — `propose_week` Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Meso generator into the runtime as a coach-callable `propose_week` tool that generates a verified week (with its own token budget) and **shows it as a non-committing preview** — no DB write, no pending, no commit (those are Slice 3b).

**Architecture:** `propose_week` is a new proposal tool. Its handler reads an LLM-declared seed (`last_week_load` + `key_type`), builds a `ContextPack` from the snapshot, runs `generate_week` with a dedicated `generation_llm` (4096 tokens, threaded via `ToolContext`), and returns `ActionProposal(type="week_proposal", ...)` whose `answer_facts` carry the week's session lines. The policy routes `week_proposal` to `answer_only` (no command), so the week flows through the existing reply path; `_must_not_claim` already blocks false write claims. Everything stays inside `runtime_v0`.

**Tech Stack:** Python 3, dataclasses, pytest, `FakeLLMClient`. Branch: `slice-3a-propose-week`.

**Spec:** `docs/superpowers/specs/2026-06-06-slice-3a-propose-week-design.md`

> **Commits:** atomic, one per task. Pre-authorized for this plan (Loïc asked for atomic commits) — proceed without re-asking.

---

## File Structure

- `backend/src/fitmas/runtime_v0/proposals.py` — **Modify**: add `"week_proposal"` to the type Literal, a `WeekProposalDraft`, and its (de)serialization.
- `backend/src/fitmas/runtime_v0/tools_read.py` — **Modify**: `ToolContext` gains `generation_llm`.
- `backend/src/fitmas/runtime_v0/meso/runtime_tool.py` — **Create**: the `propose_week` handler (builds pack, generates, returns `week_proposal`). The only Meso module that sees the runtime snapshot + proposals.
- `backend/src/fitmas/runtime_v0/tool_catalog.py` — **Modify**: register `propose_week`.
- `backend/src/fitmas/runtime_v0/policy.py` — **Modify**: `week_proposal` branch → `answer_only`.
- `backend/src/fitmas/runtime_v0/runtime.py` — **Modify**: `RuntimeDeps.generation_llm`, thread it into `ToolContext`.
- `tests/runtime_v0/test_propose_week.py` — **Create**: couche-1 tests.

---

### Task 1: `week_proposal` type + `WeekProposalDraft` (+ serialization)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/proposals.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing tests** — create `tests/runtime_v0/test_propose_week.py`:

```python
from __future__ import annotations

from fitmas.runtime_v0.proposals import (
    ActionProposal,
    WeekProposalDraft,
    proposal_from_dict,
    proposal_to_dict,
)


def _draft() -> WeekProposalDraft:
    return WeekProposalDraft(
        week_start="2026-06-08",
        source="llm",
        week_load=315.0,
        band=(300.0, 330.0),
        key_type="threshold",
        sessions=(
            {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": "3x8"},
            {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate", "detail": ""},
        ),
    )


def test_week_proposal_roundtrips():
    proposal = ActionProposal(
        type="week_proposal",
        confidence=0.8,
        user_intent_summary="week proposal",
        evidence=("semaine proposée",),
        answer_facts=("semaine proposée",),
        week_proposal=_draft(),
    )
    restored = proposal_from_dict(proposal_to_dict(proposal))
    assert restored.type == "week_proposal"
    assert restored.week_proposal == _draft()
    assert restored.week_proposal.band == (300.0, 330.0)
    assert restored.week_proposal.sessions[0]["type"] == "threshold"
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v`
Expected: FAIL — `ImportError: cannot import name 'WeekProposalDraft'`.

- [ ] **Step 3: Implement** — in `backend/src/fitmas/runtime_v0/proposals.py`:

Add the dataclass after `FactResolutionDraft`:

```python
@dataclass(frozen=True)
class WeekProposalDraft:
    week_start: str  # ISO date of the Monday the week anchors on
    source: str  # "llm" | "template_fallback"
    week_load: float
    band: tuple[float, float]
    key_type: str
    sessions: tuple[dict[str, Any], ...]  # {date, type, duration_min, intensity, detail}
```

Add `"week_proposal"` to the `ActionProposal.type` Literal (after `"fact_resolution"`):

```python
        "fact_resolution",
        "week_proposal",
        "no_send",
```

Add the field to `ActionProposal` (after `fact_resolution`):

```python
    fact_resolution: FactResolutionDraft | None = None
    week_proposal: "WeekProposalDraft | None" = None
```

In `proposal_from_dict`, reconstruct it. Add near the other locals:

```python
    week_proposal = data.get("week_proposal")
```

and add to the `ActionProposal(...)` constructor call (after the `fact_resolution=...` arg):

```python
        week_proposal=_week_proposal_from_dict(week_proposal) if week_proposal is not None else None,
```

Add the helper after `_plan_patch_from_dict`:

```python
def _week_proposal_from_dict(data: dict[str, Any]) -> WeekProposalDraft:
    return WeekProposalDraft(
        week_start=data["week_start"],
        source=data["source"],
        week_load=data["week_load"],
        band=tuple(data["band"]),
        key_type=data["key_type"],
        sessions=tuple(dict(item) for item in data.get("sessions", ())),
    )
```

(`proposal_to_dict` already serializes via `asdict`/`_jsonable` — no change needed.)

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/proposals.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): week_proposal proposal type + WeekProposalDraft

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `ToolContext.generation_llm` + the `propose_week` handler

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/tools_read.py`
- Create: `backend/src/fitmas/runtime_v0/meso/runtime_tool.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/runtime_v0/test_propose_week.py` (add imports at top):

```python
from datetime import datetime, timezone

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.meso.runtime_tool import propose_week
from fitmas.runtime_v0.snapshot import WorldSnapshot
from fitmas.runtime_v0.state import ConversationState
from fitmas.runtime_v0.tools_read import ToolContext

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # a Thursday

_GOOD_WEEK = [
    {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},   # 100
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},     # 60
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},     # 50
    {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"}, # 105
]


def _snapshot(facts=()):
    return WorldSnapshot(
        user_id=1, today=NOW.date(), now=NOW, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=facts,
        active_pending=None, recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


def _emit(sessions):
    return LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": sessions}),))


def test_propose_week_generates_and_returns_week_proposal():
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    assert proposal.type == "week_proposal"
    assert proposal.week_proposal.source == "llm"
    assert proposal.week_proposal.band == (300.0, 330.0)  # build 100->110% of 300
    assert proposal.week_proposal.week_start == "2026-06-08"  # next Monday after Thu 06-04
    assert len(proposal.week_proposal.sessions) == 4
    assert proposal.answer_facts  # week summary lines for the reply
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k generates -v`
Expected: FAIL — `ModuleNotFoundError: ... meso.runtime_tool` (and `ToolContext` has no `generation_llm`).

- [ ] **Step 3a: Implement `ToolContext.generation_llm`** — in `backend/src/fitmas/runtime_v0/tools_read.py`, extend the dataclass (it currently has `db_path`, `snapshot`, `scratchpad`):

```python
@dataclass
class ToolContext:
    db_path: Path
    snapshot: WorldSnapshot
    scratchpad: dict[str, Any] = field(default_factory=dict)
    generation_llm: Any = None  # injected LLMClient for the Meso generator (bigger token budget)
```

- [ ] **Step 3b: Implement the handler** — create `backend/src/fitmas/runtime_v0/meso/runtime_tool.py`:

```python
"""Coach-callable `propose_week` tool — the engine entry point in the runtime (Slice 3a).

The coach declares a seed (last week's load + key type, read from real recent training);
this builds a ContextPack from the snapshot and runs the Meso generator with the
injected generation_llm (bigger token budget than the chat loop). It only PROPOSES:
the returned week_proposal carries the week as answer_facts and triggers no write
(the policy routes it to answer_only). Commit/store/chaining is Slice 3b.
"""
from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.context import constraints_from_snapshot
from fitmas.runtime_v0.meso.generator import generate_week
from fitmas.runtime_v0.meso.model import ContextPack, WeekActuals, derive_continuity_target
from fitmas.runtime_v0.proposals import ActionProposal, WeekProposalDraft
from fitmas.runtime_v0.tools_proposal import _record, _trace
from fitmas.runtime_v0.tools_read import ToolContext


def _next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def propose_week(
    ctx: ToolContext,
    last_week_load: float,
    key_type: str,
    phase: str = "build",
) -> ActionProposal:
    snapshot = ctx.snapshot
    actuals = WeekActuals(total_load=float(last_week_load), key_type=key_type)
    target = derive_continuity_target(actuals, phase)
    pack = ContextPack(
        target=target,
        last_week_actuals=actuals,
        constraints=constraints_from_snapshot(snapshot),
        signals=(),
    )
    week_start = _next_monday(snapshot.today)
    result = generate_week(ctx.generation_llm, pack, week_start)
    sessions = tuple(
        {
            "date": session.date.isoformat(),
            "type": session.type,
            "duration_min": session.duration_min,
            "intensity": session.intensity,
            "detail": session.detail,
        }
        for session in result.week.sessions
    )
    draft = WeekProposalDraft(
        week_start=week_start.isoformat(),
        source=result.source,
        week_load=result.week.week_load,
        band=target.load_band,
        key_type=key_type,
        sessions=sessions,
    )
    facts = (
        f"semaine proposée du {week_start.isoformat()} — charge {result.week.week_load} "
        f"(cible {target.load_band[0]}-{target.load_band[1]}, clé {key_type})",
    ) + tuple(
        f"{s['date']} {s['type']} {s['duration_min']}min {s['intensity']}" for s in sessions
    )
    _record(ctx, "propose_week", True)
    return ActionProposal(
        type="week_proposal",
        confidence=0.8,
        user_intent_summary="week proposal",
        evidence=facts,
        answer_facts=facts,
        week_proposal=draft,
        tool_trace=_trace(ctx),
    )
```

NOTE on `_next_monday`: `(7 - today.weekday()) % 7 or 7` gives the *next* Monday strictly after today (for Thu weekday 3 → `(7-3)%7=4` → +4 days = Mon 06-08; for a Monday → `0 or 7` → +7, next Monday). The test's `NOW` is Thu 2026-06-04 → expects 2026-06-08.

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k generates -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/tools_read.py backend/src/fitmas/runtime_v0/meso/runtime_tool.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): propose_week handler + ToolContext.generation_llm

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Register `propose_week` in the tool catalog

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/tool_catalog.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing test** — append to `tests/runtime_v0/test_propose_week.py` (add import):

```python
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.tool_catalog import for_event


def test_propose_week_registered_for_user_message():
    event = InputEvent(id="e1", user_id=1, type="user_message", text="fais-moi ma semaine", occurred_at=NOW)
    tools = {tool.name: tool for tool in for_event(event, _snapshot())}
    assert "propose_week" in tools
    schema = tools["propose_week"]
    assert schema.is_proposal is True
    assert "last_week_load" in schema.parameters["properties"]
    assert "key_type" in schema.parameters["properties"]
```

(If `InputEvent`'s constructor differs, match its real signature — check `backend/src/fitmas/runtime_v0/event.py`.)

- [ ] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k registered -v`
Expected: FAIL — `assert 'propose_week' in tools`.

- [ ] **Step 3: Implement** — in `backend/src/fitmas/runtime_v0/tool_catalog.py`:

Add to the imports from `tools_proposal` is NOT needed; instead import the handler at the top:

```python
from fitmas.runtime_v0.meso.runtime_tool import propose_week
```

Add a `ToolSchema` to the `tools` tuple in `for_event` (right after `propose_plan_patch`, before `propose_memory_update`):

```python
        ToolSchema(
            name="propose_week",
            description=(
                "Propose a full running week (Meso). First read the user's recent real "
                "training, then declare the seed: last_week_load (total minutes-weighted "
                "load of the last real week) and key_type (the prescribed key session "
                "type). The engine generates and verifies the week; it is only proposed, "
                "never committed."
            ),
            parameters=_schema(
                {
                    "last_week_load": {"type": "number", "minimum": 0},
                    "key_type": {
                        "type": "string",
                        "enum": ["easy_run", "long_run", "threshold", "intervals", "recovery_run"],
                    },
                    "phase": {"type": "string", "enum": ["build", "recovery", "taper"]},
                },
                ("last_week_load", "key_type"),
            ),
            handler=propose_week,
            is_proposal=True,
        ),
```

Note: the `move_session` restricted allow-list near the end of `for_event` does NOT include `propose_week`, which is correct (a move-in-progress shouldn't trigger week generation) — leave it as is.

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k registered -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/tool_catalog.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): register propose_week as a coach-callable tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Policy routes `week_proposal` to `answer_only` (no write)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/policy.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing test** — append to `tests/runtime_v0/test_propose_week.py` (add import):

```python
from fitmas.runtime_v0.policy import RuntimePolicy


def test_policy_shows_week_proposal_without_commit():
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    decision = RuntimePolicy().evaluate(proposal, _snapshot())
    assert decision.action == "answer_only"
    assert decision.commands == ()  # 3a never writes
    assert decision.reply_facts == proposal.answer_facts
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k policy_shows -v`
Expected: FAIL — `_evaluate_type` hits the `else` → `block`/`unknown_proposal_type`.

- [ ] **Step 3: Implement** — in `backend/src/fitmas/runtime_v0/policy.py`, add a branch in `_evaluate_type` (right after the `ask_clarification` block, before `if proposal.type == "memory_update"`):

```python
        if proposal.type == "week_proposal":
            # 3a: show the proposed week, never write. The week rides in answer_facts;
            # _must_not_claim already blocks "c'est fait" since no command is applied.
            # (3b will route this to create_pending + confirmation -> commit.)
            return _decision("answer_only", "week_proposal", "low", (), proposal.answer_facts)
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k policy_shows -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/policy.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): policy shows week_proposal (answer_only, no write) in 3a

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `RuntimeDeps.generation_llm` threaded into `ToolContext` + agent integration test

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/runtime.py`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/runtime_v0/test_propose_week.py` (add import):

```python
from fitmas.runtime_v0.agent import CoachAgent


def test_coach_calls_propose_week_end_to_end():
    # Coach LLM asks for a week; generation LLM emits the typed week.
    coach_llm = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
    ])
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    snapshot = _snapshot()
    ctx = ToolContext(db_path=None, snapshot=snapshot, generation_llm=generation_llm)
    event = InputEvent(id="e1", user_id=1, type="user_message", text="fais-moi ma semaine", occurred_at=NOW)
    proposal = CoachAgent(coach_llm, "sys").run(event, snapshot.header(), for_event(event, snapshot), max_steps=3, tool_context=ctx)
    assert proposal.type == "week_proposal"
    assert proposal.week_proposal.source == "llm"
    # the generation client was used, not the coach client
    assert len(generation_llm.requests) == 1
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -k end_to_end -v`
Expected: PASS already IF Tasks 2-3 wired correctly (the agent calls the handler, which uses ctx.generation_llm). If it FAILS because `RuntimeDeps` lacks `generation_llm` (only relevant when `handle_event` builds the ctx), proceed to Step 3 to thread it through the real runtime path.

- [ ] **Step 3: Implement** — in `backend/src/fitmas/runtime_v0/runtime.py`:

Add `generation_llm` to `RuntimeDeps` (after `reply_llm`):

```python
@dataclass(frozen=True)
class RuntimeDeps:
    db_path: Path
    coach_llm: LLMClient
    reply_llm: LLMClient
    generation_llm: LLMClient | None = None
    max_steps: int = 6
```

In `_handle_new_event`, thread it into the `ToolContext` (the line currently is `ctx = ToolContext(deps.db_path, snapshot, {})`):

```python
    ctx = ToolContext(deps.db_path, snapshot, {}, generation_llm=deps.generation_llm)
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v` → all PASS. Then `.venv/bin/python -m pytest tests/runtime_v0 -q` → no regression.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/runtime.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): thread generation_llm through RuntimeDeps into ToolContext

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Full suite, LOC bump, docs

**Files:**
- Modify: `tests/runtime_v0/test_import_boundaries.py`, `docs/BUILD-ORDER.md`, `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`

- [ ] **Step 1: Run the full suite** — `.venv/bin/python -m pytest tests/runtime_v0 -q`. Record the count; must be all green.

- [ ] **Step 2: Measure core LOC and bump the cap** — run:
```bash
find backend/src/fitmas/runtime_v0 -name '*.py' -not -path '*__pycache__*' -not -path '*adapters*' -not -name '* 2.py' -print0 | xargs -0 wc -l | tail -1
```
Record `N`. In `tests/runtime_v0/test_import_boundaries.py`, raise `assert loc <= 3960` to `assert loc <= <CAP>` where `<CAP>` = N rounded up to the next 10 + 10 headroom, and extend the comment:
```python
    # 3960 -> <CAP> (6 juin 2026): Slice 3a — propose_week coach-callable tool
    # (runtime_tool, week_proposal type, generation_llm threading, policy branch).
```
If N > 4060, STOP and report BLOCKED with the number (don't exceed the ~4050 envelope without guidance).

- [ ] **Step 3: Update docs** — in `docs/BUILD-ORDER.md` Avancement: add **Slice 3a codée** = `propose_week` coach-callable (seed LLM-déclaré, génération avec budget tokens dédié, montre la semaine en preview, zéro write) ; pointer le design `2026-06-06-slice-3a-propose-week-design.md` ; suite immédiate = **Slice 3b** (confirmation → commit + store typé + chaînage). Update the "core : NNNN LOC (cap NNNN ...)" and "tests : NNN passed" numbers. In `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`, the slice-table row **3 — Tool runtime** gets a note that 3a (montrer) est fait, 3b (commit) suit.

- [ ] **Step 4: Commit**

```bash
git add tests/runtime_v0/test_import_boundaries.py docs/BUILD-ORDER.md docs/superpowers/specs/2026-06-05-moteur-sport-plan.md
git commit -m "chore(meso): Slice 3a — budget bump + docs (propose_week shown)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `propose_week` coach-callable tool, LLM-declared seed → Tasks 2, 3. ✅
- Builds ContextPack from snapshot + seed, runs generate_week → Task 2. ✅
- Dedicated `generation_llm` (4096) threaded via ToolContext / RuntimeDeps → Tasks 2, 5. ✅
- New `week_proposal` type + `WeekProposalDraft` + serialization → Task 1. ✅
- Policy → `answer_only` (no command, no write) → Task 4. ✅
- Reply via existing path (answer_facts → reply_facts; `_must_not_claim` guards write claims) → Task 4 (no reply.py change, by design). ✅
- Shows the week, never commits → Tasks 2/4 (no command emitted). ✅
- Isolation (all imports internal to runtime_v0) → Task 2 (runtime_tool imports meso.* + proposals + tools_read + tools_proposal). ✅
- Couche-1 tests (handler, policy, agent integration, serialization) → Tasks 1-5. ✅
- LOC bump → Task 6. ✅

**Placeholder scan:** no TBD/TODO. Two "match the real signature if it differs" notes (InputEvent constructor, `_next_monday` behavior) are verification instructions, not placeholders — the code is concrete.

**Type consistency:** `WeekProposalDraft{week_start, source, week_load, band, key_type, sessions}` identical across Tasks 1-2; `propose_week(ctx, last_week_load, key_type, phase="build")` signature matches the tool schema's params (Task 3) and the handler (Task 2); `ToolContext.generation_llm` introduced in Task 2 and populated in Task 5; `RuntimePolicy` `answer_only` decision shape matches the existing `_decision(...)` signature.

**Note on Task 5 Step 2:** the agent-integration test likely passes before the runtime.py change (the test builds the ToolContext directly). The runtime.py change is still required so the REAL `handle_event` path populates `generation_llm` — Task 5 covers both; the commit is justified by the runtime wiring even if the test was already green.
