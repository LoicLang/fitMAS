---
summary: implementation plan for Decision Runtime Phase 9A legacy physical delete
read_when:
  - deleting legacy Decision Runtime routes after fallback census
  - removing old CoachDecision planning cutover paths
  - checking why FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER was retired
---

# Decision Runtime Phase 9A Legacy Physical Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the first physically dead legacy runtime route after Phase 8Y by deleting the old `CoachDecision` planning cutover path.

**Architecture:** Do not delete broad `legacy/` files while fallback census still shows active owners. Phase 9A removes only the old opt-in planning cutover route from `CoachDecision` because covered planning lanes now prove canonical handling through `canonical_planning_provider.result=handled` and `legacy_skipped=true`.

**Tech Stack:** Python, pytest architecture tests, existing smoke scripts and fallback census traces.

---

### Task 1: Census Before Delete

**Files:**
- Inspect: smoke DB `conversation_turns.context_json`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [x] **Step 1: Run covered planning smoke with DB kept**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9a-census.db --scenario move_hard_close --scenario move_easy_then_confirm --scenario swap_by_day --timeout 420
```

Observed first: one `move_easy_then_confirm` run failed because
`CoachUnderstanding.requested_change.source_ref` used the machine-looking alias
`session_id_3`, which was not accepted by the canonical planning ref contract.
Fixed before deletion by centralizing typed planning ref normalization in
`domain/planning/reference_tokens.py`.

- [x] **Step 2: Inspect fallback census**

Run a query over `conversation_turns.context_json` to verify covered lanes have canonical planning handled traces and no active `fallback_census` entries.

Verified after the ref fix: the isolated `move_easy_then_confirm` smoke records
`canonical_planning_provider.result=handled` and `legacy_decide.legacy_skipped=true`.

### Task 2: Delete Old Legacy Planning Cutover Route

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/legacy/conversation_planning_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_understanding_bridge.py`
- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `scripts/smoke-decision-runtime-canonical-planning`
- Modify tests referencing the retired flag/helper.

- [x] **Step 1: Write failing architecture test**

Add a Phase 9A architecture test proving:

```text
conversation_pipeline.py does not call maybe_handle_planning_runtime_cutover
conversation_planning_bridge.py does not define maybe_handle_planning_runtime_cutover
active runtime code no longer reads FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER
```

- [x] **Step 2: Remove the route**

Delete the old `maybe_handle_planning_runtime_cutover()` branch after legacy `CoachDecision`. Keep shared planning outcome mapping functions used by the canonical provider.

- [x] **Step 3: Update wrappers and docs**

The canonical planning wrapper should use `FITMAS_CANONICAL_PLANNING_PROVIDER=1`, not the retired planning cutover flag.

### Task 3: Verify

**Files:**
- Tests: architecture pack, planning provider tests, smoke wrapper.

- [x] **Step 1: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_phase9a_legacy_physical_delete_architecture.py tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase8t_canonical_planning_provider_architecture.py
```

- [x] **Step 2: Run real smoke**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-planning-default
```

Verified:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9a-census-final.db --scenario move_hard_close --scenario move_easy_then_confirm --scenario swap_by_day --timeout 420
./scripts/smoke-decision-runtime-canonical-planning-default
```

The targeted 3-lane census smoke and the 10-scenario default canonical
planning smoke both passed. The 10-scenario smoke still shows
`legacy_decision_contract_disabled` for `replace_swim_with_bike`, which keeps
that lane under planning-owner follow-up rather than deleting broader legacy.

- [x] **Step 3: Run backend suite**

Run:

```bash
./scripts/test-backend -q
```

Verified: `1385 passed, 11 skipped, 11 subtests passed`.
