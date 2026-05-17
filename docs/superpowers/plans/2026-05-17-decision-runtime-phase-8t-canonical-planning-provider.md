---
summary: implementation plan for Decision Runtime Phase 8T canonical planning provider
read_when:
  - implementing Decision Runtime Phase 8T
  - skipping legacy CoachDecision for planning lanes
  - default-enabling canonical requested_change planning
  - hardening PlanningCommandService pending and commit safety
---

# Decision Runtime Phase 8T Canonical Planning Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route supported planning turns directly from canonical `CoachUnderstanding.requested_change` into the planning domain runtime, without calling legacy `CoachDecision`, while preserving rollback and blocking unsafe/ambiguous changes.

**Architecture:** 8Q removed `decide()` from non-planning actionable lanes. 8R/8S removed it from read-only lanes. 8T removes it from supported planning lanes by adding a dedicated canonical planning bridge: `CoachUnderstanding(plan_change) -> RequestedPlanChange -> decide_plan_change -> PlanningCommandService -> DecisionOutcome -> ReplyComposer`. Legacy `CoachDecision` remains fallback only for unsupported or failed canonical planning until the dogfood gates are green.

**Tech Stack:** Python, pytest, existing `fitmas.decision` types, `fitmas.domain.planning`, `legacy/conversation_planning_bridge.py`, `PlanningCommandService`, deterministic smoke wrappers.

## Implementation Status — 17 mai 2026

8T-A / 8T-B / 8T-C are delivered locally.

Delivered:

- opt-in canonical planning provider bridge ;
- direct planning runtime adapter from `CoachUnderstanding` ;
- pending dedup in `PlanningCommandService` ;
- commit/pending evidence hardening in planning outcomes ;
- deterministic smoke wrapper ;
- real API/LLM dogfood under `FITMAS_CANONICAL_PLANNING_PROVIDER=1` ;
- pre-decide candidate flow preemption for supported canonical planning ;
- active pending canonical resolution before candidate flow, with one safety
  recheck before write ;
- provider ref normalization for `session:*` and structured ref objects ;
- architecture docs updated.

Not delivered yet:

- default-on `FITMAS_CANONICAL_PLANNING_PROVIDER`.

---

## CTO Decision

8T is the risky slice.

Do not start by deleting legacy planning. First make the canonical planning path
stand on its own and prove it cannot:

```text
commit without an event
create duplicate pending confirmations
fallback silently to another planning route
accept fuzzy references as deterministic truth
claim a mutation that did not happen
```

## What 8T Changes

Today after 8S:

```text
non-planning actionable -> canonical, skip decide()
read-only -> canonical, skip decide()
planning -> still usually calls legacy decide()
```

8T target:

```text
planning supported by canonical Understanding
-> skip legacy decide()
-> run planning domain runtime directly
-> CommandService applies/pends/blocks
-> ReplyComposer explains outcome
```

## Explicit Non-Goals

- Do not build Phase B progression/prescription.
- Do not let the LLM produce `PlanPatch`.
- Do not broaden deterministic parsing of free text.
- Do not delete legacy provider fallback in the first sub-slice.
- Do not introduce another planning writer.
- Do not change heartbeat planning in this slice unless tests prove it already uses the same runtime path.

## New Boundary

Create one planning provider bridge:

```text
legacy/conversation_canonical_planning_bridge.py
```

It owns:

```text
FITMAS_CANONICAL_PLANNING_PROVIDER
should_use_canonical_planning_without_legacy(...)
handle_canonical_planning(...)
canonical planning trace
fallback contract
```

It must not own:

```text
candidate construction
evaluation
policy
DB writes
reply wording
free-text reference parsing
```

Those remain in:

```text
domain/planning/*
PlanningCommandService
DecisionReplyComposer
Understanding LLM
```

## Flags

Introduce:

```text
FITMAS_CANONICAL_PLANNING_PROVIDER
```

Phase 8T-A:

```text
default=False
```

Future default-on slice, after explicit CTO decision:

```text
default=True with opt-out 0
```

Keep existing:

```text
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER
```

But 8T should stop relying on the old pattern where legacy `CoachDecision`
must run first just so planning can consume canonical Understanding.

## Admissibility Gate

Canonical planning may skip legacy only if all are true:

```text
understanding.intent == "plan_change"
understanding.requested_change is not None
no active pending confirmation
no pending_resolution
no command signals that would write memory/execution first
requested_change.kind in supported kinds
source/target refs are typed enough for ReferenceResolver
```

Supported kinds for first pass:

```text
move
swap
lighten
replace
create
```

Unsupported or ambiguous:

```text
unknown
remove_optional
missing source where required
missing target where required
free-text refs such as "seance dure" not normalized by Understanding
```

For unsupported/ambiguous, 8T must choose one of two explicit outcomes:

```text
fallback_legacy
or plan_blocked / clarification
```

No silent route through another planning branch.

## Required Hardening Before Default-On

### 1. Duplicate Pending

`PlanningCommandService` must avoid creating duplicate active pending rows for
the same user and canonical plan patch payload.

Acceptance:

```text
same requested_change + same selected patch + active pending exists
-> returns existing pending id
-> does not insert a second pending row
```

### 2. Commit Evidence

A canonical planning commit is valid only if:

```text
PlanningCommandResult.status == "applied"
event_count > 0
service_result contains mutation event evidence
```

Otherwise:

```text
DecisionOutcome kind must not be plan_committed
reply_contract must forbid committed claims
```

### 3. Pending Evidence

A canonical pending is valid only if:

```text
PlanningCommandResult.status == "pending"
pending_confirmation_id is not None
```

Otherwise:

```text
block
```

### 4. No Legacy Fallthrough For Applicable Planning

If canonical planning is applicable and fails inside the runtime:

```text
block with explicit planning_runtime_unhandled
```

Do not fall through to:

```text
CoachDecision plan_patch
MutationDecision
candidate fallback
legacy pending
```

## File Structure

**Create**

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - canonical planning provider gate and pipeline adapter.

- `tests/test_conversation_canonical_planning_bridge.py`
  - unit tests for gate, direct runtime call, fallback/block behavior.

- `tests/test_phase8t_canonical_planning_provider_architecture.py`
  - static tests for ordering, flags, no legacy fallthrough, deterministic smoke.

- `scripts/smoke-decision-runtime-canonical-planning-provider`
  - deterministic wrapper first.

**Modify**

- `backend/src/fitmas/conversation_pipeline.py`
  - route canonical planning before `run_legacy_coach_decision(...)`.

- `backend/src/fitmas/domain/planning/mutation_service.py`
  - pending dedup and evidence payload hardening.

- `backend/src/fitmas/legacy/planning_runtime_adapter.py`
  - optionally expose direct `run_planning_runtime_attempt_from_understanding(...)`.

- `backend/src/fitmas/legacy/conversation_planning_bridge.py`
  - keep legacy artifact adapter, but make canonical direct path independent.

- Docs:
  - `docs/DECISION-RUNTIME-REFACTOR.md`
  - `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
  - `docs/BUILD-ORDER.md`

## Task 1: Canonical Planning Gate

**Files:**
- Create: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [ ] **Step 1: Write failing gate tests**

Add tests proving:

```python
def test_canonical_planning_provider_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    assert bridge.canonical_planning_provider_enabled() is False


def test_gate_accepts_supported_plan_change_when_flag_on(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_plan_change(kind="move", source_ref="session_id:42", target_ref="date:2026-05-18"),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation"),
        pending_confirmation=None,
    )


def test_gate_rejects_active_pending(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_plan_change(kind="move", source_ref="session_id:42", target_ref="date:2026-05-18"),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation"),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_gate_rejects_free_text_refs(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_plan_change(kind="move", source_ref="seance dure", target_ref="vendredi"),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation"),
        pending_confirmation=None,
    )
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py
```

Expected:

```text
ImportError or AttributeError for missing bridge/functions
```

- [ ] **Step 3: Implement gate only**

Implement:

```text
canonical_planning_provider_enabled(default=False)
should_use_canonical_planning_without_legacy(...)
_requested_change_refs_are_typed(...)
```

No DB. No writes. No composer yet.

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py
```

Expected:

```text
gate tests pass
```

## Task 2: Direct Planning Runtime Attempt From Understanding

**Files:**
- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [ ] **Step 1: Write failing test**

Test that direct canonical planning does not require a `LegacyCoachDecisionArtifact`:

```python
def test_handle_canonical_planning_calls_runtime_without_legacy_decision(monkeypatch):
    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(applicable=True, result=_planning_result("block"), reason="handled")

    monkeypatch.setattr(bridge, "run_planning_runtime_attempt_from_understanding", fake_attempt)

    outcome = bridge.handle_canonical_planning(
        understanding=_plan_change(kind="move", source_ref="session_id:42", target_ref="date:2026-05-18"),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace demain",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
        grounding_facts=(),
        decision_reply_composer_fn=lambda: FakeComposer(),
        turn_context={},
    )

    assert calls
    assert calls[0]["understanding"].requested_change.source_ref == "session_id:42"
    assert outcome.response_mode == "planning_runtime_block"
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py::test_handle_canonical_planning_calls_runtime_without_legacy_decision
```

Expected:

```text
AttributeError for handle_canonical_planning or direct attempt helper
```

- [ ] **Step 3: Extract direct helper**

Add to `legacy/planning_runtime_adapter.py`:

```text
run_planning_runtime_attempt_from_understanding(...)
```

It should call:

```text
decide_plan_change(understanding.requested_change, ...)
PlanningCommandService(...).apply(...)
```

It should return `PlanningRuntimeAdapterAttempt`.

Then make `run_planning_runtime_attempt_from_legacy_decision(...)` delegate to
the direct helper after adapting legacy artifact to `CoachUnderstanding`.

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_conversation_planning_runtime_adapter.py
```

Expected:

```text
all pass
```

## Task 3: Pending Dedup In PlanningCommandService

**Files:**
- Modify: `backend/src/fitmas/domain/planning/mutation_service.py`
- Test: `tests/test_domain_planning_mutation_service.py`

- [ ] **Step 1: Write failing test**

Add a test that creates an active pending confirmation, calls
`PlanningCommandService.apply(...)` for the same decision, and asserts:

```text
one pending row exists
same pending_confirmation_id returned
status == "pending"
payload["deduped"] is True
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_mutation_service.py -k pending
```

Expected:

```text
duplicate row or missing dedup payload
```

- [ ] **Step 3: Implement dedup**

Before `repo.create_pending_mutation_confirmation(...)`, compute:

```text
mutation_type
decision_json
active pending for user with same mutation_type + decision_json
```

If found:

```text
return PlanningCommandResult(status="pending", pending_confirmation_id=existing.id, payload={"deduped": True, ...})
```

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_mutation_service.py
```

Expected:

```text
all pass
```

## Task 4: Wire Canonical Planning Before Legacy Decide

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_phase8t_canonical_planning_provider_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create tests proving:

```python
def test_8t_pipeline_routes_canonical_planning_before_legacy_decide():
    source = _source("conversation_pipeline.py")
    planning_index = source.index("should_use_canonical_planning_without_legacy(")
    legacy_index = source.index("run_legacy_coach_decision(")
    assert planning_index < legacy_index


def test_8t_planning_provider_flag_starts_opt_in():
    source = _source("legacy/conversation_canonical_planning_bridge.py")
    assert "FITMAS_CANONICAL_PLANNING_PROVIDER" in source
    assert 'default=False' in source


def test_8t_no_direct_legacy_planpatch_write_from_pipeline():
    source = _source("conversation_pipeline.py")
    assert "apply_patch_for_user(" not in _active_planning_turn_section(source)
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8t_canonical_planning_provider_architecture.py
```

Expected:

```text
fails because pipeline has no canonical planning bridge
```

- [ ] **Step 3: Wire pipeline**

Order inside `conversation_pipeline.py` after canonical Understanding:

```text
1. non-planning actionable 8Q
2. read-only 8R/8S
3. canonical planning 8T
4. legacy decide fallback
```

If 8T branch returns an outcome:

```text
legacy_decision_artifact = None
skip action/pending/planning legacy branches
```

If 8T branch is applicable but fails:

```text
return planning_runtime_unhandled/block outcome
do not run legacy decide
```

If 8T branch is not applicable:

```text
legacy decide fallback
```

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_phase8t_canonical_planning_provider_architecture.py tests/test_conversation_canonical_planning_bridge.py
```

Expected:

```text
all pass
```

## Task 5: Deterministic Smoke Wrapper

**Files:**
- Create: `scripts/smoke-decision-runtime-canonical-planning-provider`

- [ ] **Step 1: Add wrapper**

Script:

```bash
#!/usr/bin/env bash
set -euo pipefail

./scripts/test-backend -q \
  tests/test_phase8t_canonical_planning_provider_architecture.py \
  tests/test_conversation_canonical_planning_bridge.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_domain_planning_decision_service.py \
  tests/test_domain_planning_mutation_service.py \
  tests/test_planning_outcome_adapter.py

./scripts/smoke-decision-runtime-canonical-readonly

echo "RESULT: OK"
```

- [ ] **Step 2: Make executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-canonical-planning-provider
```

- [ ] **Step 3: Verify**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-planning-provider
```

Expected:

```text
RESULT: OK
```

## Task 6: Real Dogfood Gate Before Default-On

**Files:**
- Modify: existing smoke scripts only if deterministic gates pass.

- [ ] **Step 1: Run real planning smoke with 8T flag**

Run:

```bash
FITMAS_CANONICAL_PLANNING_PROVIDER=1 ./scripts/smoke-decision-runtime-canonical-planning
```

Required scenarios:

```text
move_easy_then_confirm
swap_by_day
lighten_tomorrow
replace_swim_with_bike
future_evening_unavailable
fatigue_tomorrow
avoid_back_to_back
swim_unavailable_two_weeks
confirm_without_pending
```

- [ ] **Step 2: If timeout/LLM failure occurs**

Do not mark 8T default-ready.

Classify:

```text
provider timeout
schema invalid
reference unresolved
candidate failed
policy blocked
commit/pending evidence missing
reply verification failure
```

- [ ] **Step 3: Default-on only after green real smoke**

Change:

```text
FITMAS_CANONICAL_PLANNING_PROVIDER default=True
```

Only if deterministic + real smoke pass.

## Task 7: Docs And Final Verification

**Files:**
- Modify:
  - `docs/DECISION-RUNTIME-REFACTOR.md`
  - `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
  - `docs/BUILD-ORDER.md`

- [ ] **Step 1: Run targeted regressions**

```bash
./scripts/test-backend -q \
  tests/test_conversation_canonical_planning_bridge.py \
  tests/test_phase8t_canonical_planning_provider_architecture.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_domain_planning_mutation_service.py \
  tests/test_core_flows.py
```

- [ ] **Step 2: Run Phase 8 architecture pack**

Include all Phase 8 tests through `test_phase8t_canonical_planning_provider_architecture.py`.

- [ ] **Step 3: Run full backend**

```bash
./scripts/test-backend
```

- [ ] **Step 4: Run diff check**

```bash
git diff --check
```

## Acceptance Criteria

8T-A complete:

```text
Canonical planning provider exists.
It is opt-in.
It skips legacy decide for supported plan_change turns.
It blocks applicable failures instead of falling through.
Pending dedup exists.
Deterministic smoke passes.
```

8T-B complete:

```text
Real planning smoke passes under FITMAS_CANONICAL_PLANNING_PROVIDER=1.
Default-on can be considered.
No commit claim without event.
No duplicate pending.
No free-text deterministic reference parsing.
```

8T-C complete:

```text
FITMAS_CANONICAL_PLANNING_PROVIDER default-on with opt-out.
CoachDecision remains fallback only for unsupported planning or provider outage.
Planning legacy deletion can be planned next.
```

## Stop Conditions

Stop and do not default-enable if:

```text
move_easy_then_confirm times out
confirmation writes without active pending
duplicate pending appears
reply says committed without event_count > 0
ReferenceResolver accepts fuzzy free text
candidate ids leak into visible reply
legacy decide runs after canonical planning applicable failure
```

## Next After 8T

```text
8U: Delete/quarantine legacy planning provider routes that are no longer fallback-worthy.
8V: Shrink conversation_pipeline around DecisionRuntimeService.
8W: Decide whether close_turn/no_send should become canonical outcome or remain terminal adapter.
```
