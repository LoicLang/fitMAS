---
summary: implementation plan for Decision Runtime Phase 8X planning coverage complete
read_when:
  - implementing Decision Runtime Phase 8X
  - migrating remaining planning candidate fallback lanes to canonical provider
  - debugging move-to-occupied-day planning requests
---

# Decision Runtime Phase 8X Planning Coverage Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the high-risk `move_hard_close` lane from legacy candidate fallback to the canonical planning provider.

**Architecture:** Use typed TurnPlan references only after LLM Understanding has established planning intent but produced non-machine refs. The backend resolves typed day refs against `ScheduledSession`; if a move targets an occupied day with exactly one session, the candidate builder produces a swap candidate instead of falling back to legacy candidates.

**Tech Stack:** Python dataclasses, existing `RequestedPlanChange`, `ReferenceResolver`, `PlanCandidateBuilder`, API smoke evaluator.

**Status 2026-05-17:** delivered locally. `move_hard_close` now goes through the canonical planning provider.

---

### Task 1: TurnPlan Move Recovery

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [x] **Step 1: Write failing test**

Add a test proving `planning_action="move_session"` plus typed source/target weekday refs can supply `RequestedPlanChange(kind="move")` when Understanding refs are free text.

- [x] **Step 2: Implement**

Extend `_requested_change_from_turn_plan()` for `move`.

### Task 2: Move To Occupied Day Builds Swap Candidate

**Files:**
- Modify: `backend/src/fitmas/domain/planning/candidate_builder.py`
- Test: `tests/test_domain_planning_decision_service.py`

- [x] **Step 1: Write failing test**

Add a test proving a move request from Thursday to an occupied Wednesday produces a `swap_sessions` patch.

- [x] **Step 2: Implement**

If `move` source is a session and target is a date with exactly one different session, build a swap patch.

### Task 3: Smoke Gate

**Files:**
- Modify: `scripts/smoke_a_plus_api.py`
- Test: `tests/test_smoke_a_plus_api.py`

- [x] **Step 1: Require canonical provider for `move_hard_close`**

Add `move_hard_close` to required canonical planning provider scenarios.

- [x] **Step 2: Verify**

Run targeted unit tests and real smoke for `move_hard_close`.

Delivered verification:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_decision_service.py tests/test_smoke_a_plus_api.py tests/test_phase8t_canonical_planning_provider_architecture.py
# 50 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario move_hard_close --timeout 420 --keep-db --db-path .tmp-8x-move-hard-2.db
# RESULT: OK (1 check)
```
