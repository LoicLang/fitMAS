---
summary: implementation plan for Decision Runtime Phase 8W fallback census
read_when:
  - implementing Decision Runtime Phase 8W
  - classifying legacy fallback paths before deleting legacy runtime
  - debugging active CoachDecision fallback after canonical providers
---

# Decision Runtime Phase 8W Fallback Census Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every active legacy fallback explicit, owned, and smoke-testable before deleting more legacy runtime.

**Architecture:** Add a small canonical fallback census in `decision/`, then let legacy bridges record why runtime fell back. This is observability and governance only: no new user-text parsing, no new planning branch, no write-path change.

**Tech Stack:** Python dataclasses/typed dicts, existing conversation turn context JSON, pytest via `./scripts/test-backend`, real API smoke wrappers.

**Status 2026-05-17:** delivered locally. Active legacy provider fallback now writes a `fallback_census` entry, and the API smoke evaluator hard-fails any active `legacy_decide` without that entry.

---

### Task 1: Canonical Fallback Census Module

**Files:**
- Create: `backend/src/fitmas/decision/fallback_census.py`
- Test: `tests/test_decision_fallback_census.py`

- [x] **Step 1: Write failing tests**

Add tests proving a fallback entry requires a known owner, a source, a reason, and that active `legacy_decide` without a census entry is reported.

- [x] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_decision_fallback_census.py
```

Expected: fail because the module does not exist.

- [x] **Step 3: Implement module**

Expose:

```python
record_fallback(turn_context, owner, source, reason, legacy_path=None, next_step=None, severity="needs_migration")
record_legacy_provider_fallback(turn_context, response_type=None, ok=None)
fallback_entries(turn_context)
unclassified_legacy_fallback_reasons(turn_context)
```

Owners are finite: `planning`, `pending`, `command`, `reply`, `readonly`, `legacy_provider`, `clarification`, `integration`.

- [x] **Step 4: Verify green**

Run the new test file.

### Task 2: Legacy Provider Records Its Fallback

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- Test: `tests/test_conversation_decide_bridge.py`

- [x] **Step 1: Write failing test**

Extend `test_run_legacy_coach_decision_records_trace` to assert `fallback_census[0]` exists with:

```text
owner=legacy_provider
source=legacy_decide
legacy_path=CoachDecision
```

Add a planning-specific test where `canonical_planning_provider.result=fallback_legacy` records owner `planning`.

- [x] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_decide_bridge.py
```

Expected: fail because the bridge does not record fallback census yet.

- [x] **Step 3: Implement bridge call**

Call `record_legacy_provider_fallback()` inside `run_legacy_coach_decision()` after the provider returns and before the turn context is persisted.

- [x] **Step 4: Verify green**

Run the bridge test file.

### Task 3: Smoke Fails Unclassified Legacy Fallback

**Files:**
- Modify: `scripts/smoke_a_plus_api.py`
- Test: `tests/test_smoke_a_plus_api.py`

- [x] **Step 1: Write failing evaluator test**

Add a scenario fixture with `legacy_decide.legacy_skipped=false` and no `fallback_census`. It must fail with:

```text
legacy fallback used without fallback census
```

- [x] **Step 2: Verify red**

Run the new smoke evaluator test.

- [x] **Step 3: Implement evaluator guard**

Use `fitmas.decision.fallback_census.unclassified_legacy_fallback_reasons()` on each turn context. Append any returned reason to `ScenarioCheckResult.reasons`.

- [x] **Step 4: Verify green**

Run `tests/test_smoke_a_plus_api.py`.

### Task 4: Docs And Verification

**Files:**
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [x] **Step 1: Update docs**

Document Phase 8W as delivered:

```text
fallback_census is the required ledger for active legacy fallback
smoke evaluator hard-fails unclassified active legacy fallback
legacy deletion waits until fallback_census is empty on dogfood lanes
```

- [x] **Step 2: Run verification**

Run:

```bash
./scripts/test-backend -q tests/test_decision_fallback_census.py tests/test_conversation_decide_bridge.py tests/test_smoke_a_plus_api.py
./scripts/smoke-decision-runtime-canonical-planning-default
./scripts/test-backend -q
git diff --check
```

Delivered verification:

```bash
./scripts/test-backend -q tests/test_decision_fallback_census.py tests/test_conversation_decide_bridge.py tests/test_smoke_a_plus_api.py
# 25 passed

./scripts/smoke-decision-runtime-canonical-planning-default
# RESULT: OK (9 checks)

./scripts/test-backend -q
# 1371 passed, 11 skipped, 11 subtests passed

git diff --check
# OK
```
