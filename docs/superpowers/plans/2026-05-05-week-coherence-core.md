---
summary: plan d implementation Phase A+ week coherence core
read_when:
  - reprendre ou auditer le chantier A+ WeekCoherenceReviewer
  - modifier la gate sportive dans PlanMutationService
  - diagnostiquer les tests week_coherence
---

# Week Coherence Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** implemented locally on 5 May 2026. The remaining unchecked boxes preserve the original execution plan, not current progress.

**Goal:** Add Phase A+ core so significant `PlanPatch` commits pass through deterministic week simulation, an LLM-style sport quality review contract, and backend policy before `PlanMutationService` writes.

**Architecture:** Create `fitmas.week_coherence` as a pure domain module for simulation, deterministic checks, review parsing, fallback, and policy aggregation. Then wire `apply_patch_for_user()` so the week gate can block or require confirmation before any commit. Keep the runtime integration injectable and conservative: tests use a fake reviewer, production calls the LLM reviewer through `llm_gateway` and falls back deterministically if the provider returns nothing or invalid JSON.

**Tech Stack:** Python 3.13, dataclasses, Pydantic `PlanPatch`, SQLAlchemy repository access, existing `./scripts/test-backend` runner.

---

### Task 1: Week Coherence Pure Core

**Files:**
- Create: `backend/src/fitmas/week_coherence.py`
- Test: `tests/test_week_coherence.py`

- [ ] **Step 1: Write failing tests**

Add tests for:
- `simulate_plan_patch()` moves a session in the after snapshot without mutating the original object.
- `simulate_plan_patch()` replaces sport/type/title/duration/intensity.
- `evaluate_week_invariants()` detects key session touched, recovery count delta, hard-session gap, duration delta.
- `aggregate_week_coherence_policy()` preserves runtime hard block and lets reviewer raise confirmation/block.

Run: `./scripts/test-backend tests/test_week_coherence.py -q`
Expected: fail because `fitmas.week_coherence` does not exist.

- [ ] **Step 2: Implement minimal pure core**

Create dataclasses from `docs/SPORT-QUALITY-REVIEW.md`:
- `WeekSnapshot`
- `WeekPatchDiff`
- `DeterministicWeekChecks`
- `WeekCoherenceFinding`
- `WeekCoherenceReview`
- `WeekCoherenceContext`

Implement:
- `simulate_plan_patch`
- `evaluate_week_invariants`
- `aggregate_week_coherence_policy`
- helpers for date parsing, session snapshots, role detection.

- [ ] **Step 3: Verify**

Run: `./scripts/test-backend tests/test_week_coherence.py -q`
Expected: pass.

### Task 2: Review Parsing And Fallback

**Files:**
- Modify: `backend/src/fitmas/week_coherence.py`
- Test: `tests/test_week_coherence.py`

- [ ] **Step 1: Write failing tests**

Add tests for:
- `review_week_coherence_with_llm()` accepts typed JSON from an injected `request_json_fn`.
- invalid reviewer JSON falls back to deterministic review instead of silently accepting.
- fallback review returns `requires_confirmation` for warning validation or risk flags.

Run: `./scripts/test-backend tests/test_week_coherence.py -q`
Expected: fail because review function is missing or incomplete.

- [ ] **Step 2: Implement minimal review wrapper**

Implement:
- `review_week_coherence_with_llm(context, request_json_fn=None)`
- `fallback_week_coherence_review(context, reason=...)`
- strict coercion of status, sport_quality, findings, recommended_policy.

If `request_json_fn` is `None`, return deterministic fallback. This keeps runtime safe until provider wiring is explicit.

- [ ] **Step 3: Verify**

Run: `./scripts/test-backend tests/test_week_coherence.py -q`
Expected: pass.

### Task 3: PlanMutationService Gate

**Files:**
- Modify: `backend/src/fitmas/plan_mutation_service.py`
- Test: `tests/test_plan_mutation_service.py`

- [ ] **Step 1: Write failing tests**

Add tests for:
- reviewer `requires_confirmation` prevents commit when `allow_requires_confirmation=False`.
- reviewer `blocked` prevents commit.
- `allow_requires_confirmation=True` allows a confirmable review to proceed.
- runtime `blocked` validation still bypasses reviewer and does not commit.

Run: `./scripts/test-backend tests/test_plan_mutation_service.py -q`
Expected: fail because `PlanPatchServiceResult` has no week review and `apply_patch_for_user()` does not call the gate.

- [ ] **Step 2: Implement gate**

Modify:
- `PlanPatchServiceResult` with `week_review: WeekCoherenceReview | None = None` and `week_policy_status: str | None = None`.
- `apply_patch_for_user()` to call a new helper `_review_patch_week_coherence()` after runtime validation allows possible commit and before applying operations.
- `_review_patch_week_coherence()` loads recent activities/facts lightly, builds context, calls `review_week_coherence_with_llm()` with default fallback, aggregates policy.

Keep the helper injectable enough for tests by monkeypatching `fitmas.plan_mutation_service.review_week_coherence_with_llm`.

- [ ] **Step 3: Verify**

Run: `./scripts/test-backend tests/test_plan_mutation_service.py -q`
Expected: pass.

### Task 4: Conversation Pending Behavior Compatibility

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py` only if needed
- Test: targeted existing tests around plan patch confirmation

- [ ] **Step 1: Run existing tests**

Run: `./scripts/test-backend tests/test_blocked_mutation_reply.py tests/test_llm_tools.py::TestLLMTools -q`
Expected: identify any assumptions broken by `PlanPatchServiceResult.week_review`.

- [ ] **Step 2: Patch only if failing**

If existing pending/reply helpers need richer summaries, update them to prefer week review summary when policy is confirm/block.

- [ ] **Step 3: Verify**

Re-run the failing targeted tests.

### Task 5: Documentation And Final Verification

**Files:**
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/SPORT-QUALITY-REVIEW.md`

- [ ] **Step 1: Update status docs**

Mark A+1-A+3 as implemented locally only after tests pass.

- [ ] **Step 2: Full verification**

Run:
- `./scripts/test-backend tests/test_week_coherence.py tests/test_plan_mutation_service.py -q`
- `git diff --check`

Expected: both exit 0.
