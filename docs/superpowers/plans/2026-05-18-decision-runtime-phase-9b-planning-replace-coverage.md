---
summary: implementation plan for Decision Runtime Phase 9B planning replace coverage
read_when:
  - implementing Phase 9B after legacy physical delete
  - removing planning-owner fallbacks from canonical dogfood lanes
  - debugging replace_swim_with_bike or replace_session canonical planning
---

# Decision Runtime Phase 9B Planning Replace Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `replace_swim_with_bike` dogfood lane canonical, so it no longer reaches `legacy_decision_contract_disabled`.

**Architecture:** Keep the fix inside the canonical planning lane: `CoachUnderstanding` / typed `TurnPlan` artifacts feed `RequestedPlanChange`, `PlanCandidateBuilder` builds a bounded `replace_session` candidate, policy decides commit/pending/block, and `PlanningCommandService` writes or stores pending. Do not revive `CoachDecision -> PlanPatch` planning authority.

**Tech Stack:** Python, pytest, FastAPI smoke harness, existing Decision Runtime planning modules.

---

### Task 1: Census The Replace Gap

**Files:**
- Inspect: `.tmp-9b-replace-census.db`
- Inspect: `scripts/smoke_a_plus_api.py`
- Modify: this plan doc

- [x] **Step 1: Run the real replace smoke with DB kept**

```bash
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9b-replace-census.db --scenario replace_swim_with_bike --timeout 420
```

- [x] **Step 2: Classify the fallback**

Query `conversation_turns.context_json` and capture:

```text
response_mode
canonical_planning_provider.result
canonical_planning_provider.fallback_reason
fallback_census owner/source/reason
```

Observed before fix:

```text
response_mode=legacy_decision_contract_disabled
canonical_planning_provider.result=fallback_legacy
canonical_planning_provider.fallback_reason=unsupported_requested_change, then blocking_command_signals
fallback_census owner=planning source=canonical_planning_provider reason=blocking_command_signals
```

### Task 2: Add Red Tests For Canonical Replace

**Files:**
- Modify: `tests/test_conversation_canonical_planning_bridge.py`
- Modify: `tests/test_domain_planning_candidate_builder.py`
- Modify: `tests/test_smoke_a_plus_api.py` or `tests/test_phase9a_legacy_physical_delete_architecture.py`

- [x] **Step 1: Test TurnPlan fallback can build replace**

Add a test proving a `replace_session` TurnPlan plus temporal target `sunday` and typed desired sport creates:

```text
RequestedPlanChange(kind="replace", source_ref="day:sunday", desired_sport="cycling")
```

- [x] **Step 2: Test replace candidate preserves sport intent**

Add a test proving `PlanCandidateBuilder` turns that request into:

```text
operation_type="replace_session"
new_sport_type="cycling"
new_session_type in {"easy", "support"}
new_intensity="easy"
```

- [x] **Step 3: Verify tests fail before code**

Run the two targeted tests and confirm the failure is missing replace support, not a typo.

### Task 3: Implement Canonical Replace Coverage

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Modify if needed: `backend/src/fitmas/domain/planning/candidate_builder.py`

- [x] **Step 1: Let TurnPlan supplement replace requests**

Extend `_requested_change_from_turn_plan()` for `replace_session`:

```text
source_ref = machine source ref, else temporal source/target ref, else fallback source
desired_sport = fallback requested desired_sport if present
desired_intensity = fallback requested desired_intensity if present, else easy
```

- [x] **Step 2: Keep deterministic work on typed artifacts only**

Do not parse free user text. Only use:

```text
CoachUnderstanding.requested_change
TurnPlan.planning_action
TurnPlan.temporal_references
structured desired_* fields
```

### Task 4: Gates And Smokes

**Files:**
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`

- [x] **Step 1: Run unit gates**

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_candidate_builder.py tests/test_smoke_a_plus_api.py -k "replace or canonical_planning"
```

Verified broader targeted gate:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_candidate_builder.py tests/test_planning_outcome_adapter.py tests/test_legacy_final_reply_backend.py tests/test_smoke_a_plus_api.py -k "replace or canonical_planning"
```

Result: `32 passed, 30 deselected`.

- [x] **Step 2: Run real replace smoke**

```bash
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9b-replace-final.db --scenario replace_swim_with_bike --timeout 420
```

Verified final run:

```text
response_mode=planning_runtime_pending_confirmation
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
fallback_census=None
reply="Je te propose: remplacer la seance ciblee par velo facile, 30 min. Tu confirmes ?"
```

- [x] **Step 3: Run default canonical planning smoke**

```bash
./scripts/smoke-decision-runtime-canonical-planning-default
```

Result: `RESULT: OK (10 check(s))`.

Follow-up found during the final gate:

```text
day:tomorrow
-> ReferenceResolver resolves the typed relative ref against CoachContext.local_time
-> empty target blocks with a user-safe date reason
-> no raw unresolved_source_ref leaks to the reply
```

- [x] **Step 4: Run backend suite**

```bash
./scripts/test-backend -q
```

Result: `1393 passed, 11 skipped, 11 subtests passed`.
