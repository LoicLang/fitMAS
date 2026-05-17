---
summary: implementation plan for Decision Runtime Phase 7 heartbeat through DecisionRuntime
read_when:
  - implementing Decision Runtime Phase 7
  - migrating heartbeat, weekly review or proactive coach loops
  - changing telegram scheduler delivery
  - routing proactive drafts through InputEvent and DecisionOutcome
  - moving telegram scheduler code toward backend/src/fitmas/app/telegram
---

# Decision Runtime Phase 7 Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make heartbeat/proactive coach triggers enter the canonical loop as `InputEvent -> DecisionOutcome -> delivery`, without rewriting the full heartbeat reasoning stack in one risky move.

**Architecture:** Phase 7 is a cutover bridge. The current heartbeat implementation stays available as legacy behavior, but every proactive trigger gets a canonical event and an outcome. Scheduler delivery moves toward the target `app/telegram/` organization. The new adapter lives outside `decision/` because it imports legacy heartbeat code.

**Tech Stack:** Python 3.13, dataclasses, existing `CoachDraft`, existing heartbeat role builders, existing Telegram scheduler, `DecisionOutcome`, pytest architecture tests, feature flags for safe rollout.

**Status 2026-05-14:** implemented locally. Heartbeat triggers now have a
legacy runtime adapter that emits `InputEvent` and `DecisionOutcome`; scheduler
lives under `fitmas.app.telegram.scheduler` with root compatibility; scheduler,
manual `/heartbeat`, debug heartbeat and ops heartbeat can use the adapter
behind `FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1`. Existing heartbeat internals remain
legacy until Phase 8. During verification, the real smoke exposed that typed
execution `target_ref` values can be ISO dates; `execution_mutation_service`
now resolves `YYYY-MM-DD` and `date:YYYY-MM-DD` against `ScheduledSession`.

## Current State

Heartbeat is still a parallel runtime:

```text
telegram_scheduler.py
-> fitmas.heartbeat.morning_briefing / pre_session_reminder / weekly_review
-> skills/heartbeat/heartbeat.py
-> heartbeat prompt/tool loop/final_reply/guards
-> CoachDraft
-> Telegram send + persist_draft_for_owner
```

Important current files:

```text
backend/src/fitmas/heartbeat.py
  compatibility alias to fitmas.skills.heartbeat.heartbeat

backend/src/fitmas/skills/heartbeat/heartbeat.py
  main heartbeat runtime, LLM generation, proactive gates, heartbeat-specific guards

backend/src/fitmas/telegram_scheduler.py
  scheduler, send lock, Telegram send, persistence after successful send

backend/src/fitmas/telegram_commands.py
  manual /heartbeat command

backend/src/fitmas/api_debug.py
backend/src/fitmas/api_ops.py
  debug/ops heartbeat entrypoints
```

Decision runtime already has the primitives Phase 7 needs:

```text
decision/input_event.py      InputEvent(source="scheduler", type="heartbeat_tick" | "weekly_review_tick")
decision/outcome.py          DecisionOutcome(kind="answer" | "plan_pending" | "no_send")
decision/reply_composer.py   common visible reply entrypoint
decision/output_verifier.py  common visible reply verifier
```

## Phase 7 Boundary

Allowed:

- add a legacy heartbeat runtime adapter that converts heartbeat triggers to `InputEvent` and `DecisionOutcome`;
- create target package scaffolding under `backend/src/fitmas/app/telegram/`;
- move `telegram_scheduler.py` implementation to `backend/src/fitmas/app/telegram/scheduler.py` with a root compatibility wrapper;
- route scheduler heartbeat factories through the adapter behind `FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1`;
- support `no_send`, `answer`, and `plan_pending` outcomes for proactive triggers;
- add shadow verification with `DecisionOutputVerifier`;
- update docs and architecture tests.

Forbidden:

- no import from `fitmas.legacy` or `fitmas.skills.heartbeat` inside `fitmas.decision`;
- no rewrite of heartbeat prompts in this phase;
- no deletion of current heartbeat guards before parity is proven;
- no deterministic parser on free user text;
- no DB write inside the heartbeat runtime adapter;
- no Telegram send inside the heartbeat runtime adapter;
- no default-on cutover until scheduler tests, heartbeat tests and smoke paths are green;
- no bypass of `persist_draft_for_owner` semantics: persist only after successful Telegram send.

## Target Flow

Initial Phase 7 target:

```text
Scheduler / manual heartbeat / ops debug
  -> InputEvent(source, type, payload.trigger)
  -> LegacyHeartbeatRuntimeAdapter
  -> existing heartbeat trigger function
  -> CoachDraft | None
  -> DecisionOutcome(answer | plan_pending | no_send)
  -> DecisionOutputVerifier shadow/enforced by flag
  -> Telegram delivery persists CoachDraft only after successful send
```

Final post-Phase-8 target:

```text
Scheduler
  -> InputEvent
  -> DecisionRuntime.run(event)
  -> ContextBuilder
  -> DecisionEngine
  -> ReplyComposer
  -> OutputVerifier
  -> Delivery
```

Phase 7 should not pretend the final target is complete. It creates the bridge and makes the remaining heartbeat internals visibly legacy.

## Target File Map

Create:

```text
backend/src/fitmas/app/
  __init__.py
  telegram/
    __init__.py
    scheduler.py                  moved implementation from root telegram_scheduler.py

backend/src/fitmas/legacy/
  heartbeat_runtime_adapter.py    legacy heartbeat -> InputEvent/DecisionOutcome bridge

backend/src/fitmas/telegram_scheduler.py
  compatibility wrapper importing from fitmas.app.telegram.scheduler

tests/
  test_heartbeat_runtime_adapter.py
  test_telegram_scheduler_runtime_adapter.py
  test_phase7_heartbeat_architecture.py
```

Modify:

```text
backend/src/fitmas/telegram_commands.py   optional manual /heartbeat adapter hook
backend/src/fitmas/api_debug.py           optional debug adapter hook
backend/src/fitmas/api_ops.py             optional ops adapter hook
docs/DECISION-RUNTIME-REFACTOR.md
docs/BUILD-ORDER.md
```

## Event Contract

Use the existing `InputEvent` shape. Do not add specialized event classes unless tests prove a real need.

Payload:

```python
{
    "trigger": "morning_briefing" | "pre_session_reminder" | "weekly_review" | "signal_check",
    "delivery_channel": "telegram" | "debug" | "ops",
    "manual": bool,
    "window_status": str | None,
}
```

Mapping:

```text
morning_briefing     -> InputEvent.type = "heartbeat_tick"
pre_session_reminder -> InputEvent.type = "heartbeat_tick"
signal_check         -> InputEvent.type = "heartbeat_tick"
weekly_review        -> InputEvent.type = "weekly_review_tick"
```

Event source:

```text
scheduler cron       -> source="scheduler"
manual /heartbeat    -> source="telegram"
debug endpoint       -> source="ops"
Strava stays separate -> source="strava", type="activity_synced" in a later phase
```

## Outcome Contract

Map legacy heartbeat results conservatively:

```text
CoachDraft is None
  -> DecisionOutcome(kind="no_send")

CoachDraft without pending_confirmation
  -> DecisionOutcome(kind="answer")

CoachDraft with pending_confirmation
  -> DecisionOutcome(kind="plan_pending")
```

Do not claim committed planning mutations from heartbeat unless the adapter receives an applied event id. Current heartbeat should mostly be read-only / pending.

Reply contract examples:

```python
ReplyContract(
    mode="heartbeat_answer",
    audience="telegram",
    allowed_claims=("read_only_context", "reminder", "coach_feedback"),
    forbidden_claims=("plan_committed_without_event", "execution_updated_without_event"),
)

ReplyContract(
    mode="heartbeat_plan_pending",
    audience="telegram",
    allowed_claims=("pending_created",),
    forbidden_claims=("plan_committed", "execution_updated_without_event"),
)

ReplyContract(
    mode="heartbeat_no_send",
    audience="telegram",
    allowed_claims=(),
    forbidden_claims=("visible_reply",),
)
```

## Invariants

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 7

1. Heartbeat triggers become InputEvent before any runtime work.
2. Scheduler delivery does not call raw heartbeat functions when runtime cutover is enabled.
3. The adapter produces DecisionOutcome for send, pending and no_send.
4. No DB write happens in the adapter.
5. No Telegram send happens in the adapter.
6. decision/ imports no heartbeat, no telegram scheduler and no legacy modules.
7. Delivery still persists only after successful Telegram send.
8. Existing heartbeat behavior stays default until cutover is explicitly enabled.
9. Heartbeat-specific guards stay legacy during Phase 7; they are not duplicated in new code.
10. Any new architecture test must prevent a second proactive runtime from being added later.
```

## Task 1: Heartbeat Runtime Adapter Models

**Files:**
- Create: `backend/src/fitmas/legacy/heartbeat_runtime_adapter.py`
- Create: `tests/test_heartbeat_runtime_adapter.py`

- [ ] **Step 1: Write failing tests first**

Create tests for:

```text
test_build_heartbeat_event_uses_scheduler_source_and_heartbeat_type
test_build_weekly_review_event_uses_weekly_review_type
test_none_draft_maps_to_no_send_outcome
test_text_draft_maps_to_answer_outcome
test_pending_draft_maps_to_plan_pending_outcome
test_adapter_does_not_persist_or_deliver
```

Expected imports:

```python
from fitmas.coach_messages import CoachDraft, DraftPendingConfirmation
from fitmas.legacy.heartbeat_runtime_adapter import (
    HeartbeatRuntimeResult,
    build_heartbeat_input_event,
    heartbeat_draft_to_outcome,
    run_heartbeat_trigger,
)
```

- [ ] **Step 2: Implement minimal dataclasses**

Implementation shape:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import uuid4

from fitmas.coach_messages import CoachDraft
from fitmas.decision import DecisionExplanation, DecisionOutcome, InputEvent, ReplyContract

HeartbeatTrigger = Literal[
    "morning_briefing",
    "pre_session_reminder",
    "weekly_review",
    "signal_check",
]


@dataclass(frozen=True, slots=True)
class HeartbeatRuntimeResult:
    event: InputEvent
    outcome: DecisionOutcome
    draft: CoachDraft | None
    reply_text: str | None
    verifier_reason: str | None = None
```

Keep it boring. This is a bridge, not a second engine.

- [ ] **Step 3: Implement event builder**

Rules:

```text
trigger weekly_review -> event.type weekly_review_tick
other triggers        -> event.type heartbeat_tick
source default        -> scheduler
text                  -> None
payload               -> trigger + delivery_channel + manual + optional metadata
occurred_at           -> injected now or UTC now
id                    -> heartbeat:{trigger}:{uuid}
```

- [ ] **Step 4: Implement outcome mapper**

For `None`:

```text
kind no_send
reason_summary "No proactive message was produced."
reply_contract.mode heartbeat_no_send
```

For normal draft:

```text
kind answer
reason_summary draft.text
reply_contract.mode heartbeat_answer
```

For pending draft:

```text
kind plan_pending
reason_summary pending.summary or draft.text
next_step "await_user_confirmation"
reply_contract.mode heartbeat_plan_pending
```

Do not add `CommandResult(status="applied")` unless there is a real event id.

## Task 2: Shadow Output Verification

**Files:**
- Modify: `backend/src/fitmas/legacy/heartbeat_runtime_adapter.py`
- Extend: `tests/test_heartbeat_runtime_adapter.py`

- [ ] **Step 1: Add verifier injection**

`run_heartbeat_trigger` should accept:

```python
verifier: OutputVerifier | None = None
enforce_verifier: bool = False
```

Default behavior:

```text
run verifier if a draft text exists
store verifier_reason if blocked
if enforce_verifier is False, keep existing draft
if enforce_verifier is True and blocked, return no_send result
```

Why shadow first: current heartbeat already has specific LLM factual/claim guards. The common verifier may initially block valid proactive copy too aggressively. Shadow data tells us before we flip enforcement.

- [ ] **Step 2: Add tests**

Tests:

```text
blocked verifier in shadow mode keeps draft and records reason
blocked verifier in enforce mode returns no_send and no draft
allowed verifier keeps draft
```

No LLM calls in these tests. Use fake verifier objects.

## Task 3: Move Scheduler Toward Target Repo Organization

**Files:**
- Create: `backend/src/fitmas/app/__init__.py`
- Create: `backend/src/fitmas/app/telegram/__init__.py`
- Move: `backend/src/fitmas/telegram_scheduler.py` -> `backend/src/fitmas/app/telegram/scheduler.py`
- Recreate: `backend/src/fitmas/telegram_scheduler.py` as compatibility wrapper
- Modify: `tests/test_telegram_scheduler.py`
- Create/extend: `tests/test_phase7_heartbeat_architecture.py`

- [ ] **Step 1: Add import compatibility test**

Add to scheduler tests:

```python
def test_root_telegram_scheduler_reexports_target_scheduler_module() -> None:
    from fitmas import telegram_scheduler
    from fitmas.app.telegram import scheduler

    assert telegram_scheduler.register_jobs is scheduler.register_jobs
    assert telegram_scheduler._daily_target_time is scheduler._daily_target_time
```

- [ ] **Step 2: Move implementation mechanically**

Root wrapper:

```python
from __future__ import annotations

from fitmas.app.telegram.scheduler import *  # noqa: F401,F403
```

Do not move `telegram_bot.py` in this phase unless tests force it. Phase 7 only needs scheduler/delivery boundary pressure.

- [ ] **Step 3: Architecture test**

`tests/test_phase7_heartbeat_architecture.py` should assert:

```text
backend/src/fitmas/app/telegram/scheduler.py exists
backend/src/fitmas/telegram_scheduler.py is a thin wrapper
fitmas.decision imports no fitmas.app.telegram, no fitmas.telegram_scheduler, no fitmas.heartbeat
```

## Task 4: Scheduler Runtime Cutover Flag

**Files:**
- Modify: `backend/src/fitmas/app/telegram/scheduler.py`
- Create: `tests/test_telegram_scheduler_runtime_adapter.py`

- [ ] **Step 1: Add feature flag helper**

```python
def _heartbeat_runtime_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "")).strip().lower() in {"1", "true", "yes", "on"}
```

Default stays off.

- [ ] **Step 2: Add runtime factory helper**

Implementation shape:

```python
def _heartbeat_draft_factory(trigger: str, legacy_factory):
    if not _heartbeat_runtime_cutover_enabled():
        return legacy_factory

    def _factory():
        from fitmas.legacy.heartbeat_runtime_adapter import run_heartbeat_trigger

        result = run_heartbeat_trigger(
            trigger=trigger,
            legacy_factory=legacy_factory,
            source="scheduler",
            delivery_channel="telegram",
            enforce_verifier=_heartbeat_runtime_verifier_enforced(),
        )
        _log_heartbeat_runtime_result(result)
        return result.draft

    return _factory
```

Separate flag for enforcement:

```text
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1
```

- [ ] **Step 3: Wire scheduler functions**

Change:

```python
draft_factory=morning_briefing
```

to:

```python
draft_factory=_heartbeat_draft_factory("morning_briefing", morning_briefing)
```

Apply to:

```text
send_morning_briefing
send_pre_session_reminder
weekly_review_cron
```

Do not change `send_new_week_plan`; it is plan generation, not heartbeat.

- [ ] **Step 4: Tests**

Use fake factories and monkeypatch env:

```text
cutover off -> helper returns legacy factory output
cutover on -> helper calls run_heartbeat_trigger
blocked enforce -> no draft is sent
window_status is preserved in event payload for morning briefing if supplied
```

Avoid Telegram network calls. Test the factory helper and `_send_serialized_draft` with fake bot/context if needed.

## Task 5: Manual And Ops Entry Points

**Files:**
- Modify: `backend/src/fitmas/telegram_commands.py`
- Modify: `backend/src/fitmas/api_debug.py`
- Modify: `backend/src/fitmas/api_ops.py`
- Extend: `tests/test_telegram_scheduler_runtime_adapter.py` or create focused tests

- [ ] **Step 1: Manual `/heartbeat`**

Behind the same cutover flag, route manual `/heartbeat` through:

```text
InputEvent(source="telegram", type="heartbeat_tick", payload.manual=True)
```

Keep legacy behavior when flag off.

Important: command reply still sends only after result has a draft. Persistence remains after send.

- [ ] **Step 2: Debug/ops endpoints**

Debug and ops can keep direct legacy calls when `dump=true` requires legacy debug traces. Add adapter only for normal run path where possible.

Do not break existing debug trace behavior:

```text
tests/test_heartbeat_debug_endpoint.py must remain green
```

If debug trace is tightly coupled to legacy internals, document it as Phase 8/ops legacy instead of forcing a risky move.

## Task 6: Architecture Tests Against Drift

**Files:**
- Create: `tests/test_phase7_heartbeat_architecture.py`
- Extend: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: `decision/` purity**

Assert no `decision/*.py` imports:

```text
fitmas.heartbeat
fitmas.skills.heartbeat
fitmas.telegram_scheduler
fitmas.app.telegram
fitmas.coach_messages
```

- [ ] **Step 2: legacy adapter is the only new heartbeat bridge**

Assert only these files may import `fitmas.heartbeat` / `fitmas.skills.heartbeat` for Phase 7 runtime bridging:

```text
backend/src/fitmas/heartbeat.py
backend/src/fitmas/legacy/heartbeat_runtime_adapter.py
backend/src/fitmas/app/telegram/scheduler.py
backend/src/fitmas/telegram_commands.py
backend/src/fitmas/api_debug.py
backend/src/fitmas/api_ops.py
```

Keep the allow-list honest. If a file is only old pre-existing behavior, name it explicitly as legacy in the assertion message.

- [ ] **Step 3: no send/persist in adapter**

Static source test:

```text
legacy/heartbeat_runtime_adapter.py must not contain:
send_message
persist_draft
persist_draft_for_owner
SessionLocal
.commit(
.flush(
```

- [ ] **Step 4: scheduler persistence ordering**

Keep or add a behavioral test proving:

```text
send_message succeeds -> persist_draft_for_owner called
send_message raises   -> persist_draft_for_owner not called
```

This is a product-critical invariant.

## Task 7: Docs And Status

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Update status after implementation**

Add Phase 7 status:

```text
Phase 7 initiale livree localement:
- heartbeat triggers get InputEvent;
- legacy heartbeat results map to DecisionOutcome;
- scheduler cutover available behind FITMAS_HEARTBEAT_RUNTIME_CUTOVER;
- output verifier runs shadow/enforced by flag;
- app/telegram/scheduler.py starts target repo organization;
- old heartbeat internals remain legacy until Phase 8.
```

- [ ] **Step 2: Update legacy list**

Explicitly mark these as legacy after Phase 7:

```text
skills/heartbeat/heartbeat.py prompt/tool loop
heartbeat-specific final reply calls
heartbeat-specific factual/claim guards
root heartbeat.py alias
root telegram_scheduler.py wrapper
debug heartbeat trace internals
```

Do not claim they are removed.

## Verification Plan

Run targeted tests first:

```bash
./scripts/test-backend -q tests/test_heartbeat_runtime_adapter.py
./scripts/test-backend -q tests/test_telegram_scheduler.py tests/test_telegram_scheduler_runtime_adapter.py
./scripts/test-backend -q tests/test_phase7_heartbeat_architecture.py tests/test_decision_runtime_architecture.py
./scripts/test-backend -q tests/test_heartbeat_tool_loop.py tests/test_heartbeat_debug_endpoint.py tests/test_heartbeat_grounding.py
```

Then run full backend:

```bash
./scripts/test-backend -q
```

Run smoke if available in the local env:

```bash
./scripts/smoke-real-conversations --scenario heartbeat_non_completion
```

If provider credentials or real API state block smoke, record it explicitly in the final report. Do not claim smoke coverage without output.

## Rollout

Default after implementation:

```text
FITMAS_HEARTBEAT_RUNTIME_CUTOVER unset -> old behavior
FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1 -> scheduler/manual paths use adapter
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE unset -> verifier shadow only
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1 -> blocked common verifier suppresses send
```

Recommended dogfood order:

```text
1. cutover off, tests green
2. cutover on locally, verifier shadow
3. compare morning briefing / reminder / weekly review debug traces
4. enable verifier enforcement only after blocked reasons are reviewed
5. Phase 8 removes legacy internals once parity is proven
```

## Risks

**Risk: common verifier blocks valid heartbeat copy.**
Mitigation: shadow first, enforcement flag separate from runtime cutover.

**Risk: pending confirmation persistence breaks.**
Mitigation: keep `CoachDraft.pending_confirmation` delivery contract intact. Scheduler still persists the draft only after successful send.

**Risk: moving scheduler breaks imports.**
Mitigation: root wrapper and import compatibility tests.

**Risk: adapter becomes a new runtime instead of a bridge.**
Mitigation: no DB, no send, no prompt, no policy, no writes in adapter. It only maps legacy output to canonical event/outcome.

**Risk: false sense of architecture completion.**
Mitigation: docs must explicitly say heartbeat internals remain legacy after Phase 7.

## Acceptance Criteria

```text
1. New plan file exists with this Phase 7 checklist.
2. Heartbeat events are represented as InputEvent.
3. Legacy heartbeat output is represented as DecisionOutcome.
4. Scheduler can route heartbeat through the adapter behind a flag.
5. Delivery persistence order stays unchanged.
6. decision/ remains pure and imports no heartbeat/scheduler/legacy code.
7. app/telegram/scheduler.py exists, with root telegram_scheduler.py as compat wrapper.
8. Existing heartbeat grounding/tool/debug tests remain green.
9. Full backend test suite passes.
10. Docs clearly mark heartbeat internals as legacy, not deleted.
```
