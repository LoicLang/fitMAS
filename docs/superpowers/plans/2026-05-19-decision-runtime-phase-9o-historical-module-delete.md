---
summary: Phase 9O plan for physically deleting dead historical planning modules after zero fallback census
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9M/9N
  - deleting planning_snapshot, adaptation_proposal, or plan_patch_candidate_generator
  - preventing historical planning routes from returning to runtime or tests
---

# Decision Runtime Phase 9O Historical Module Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Physically delete the dead historical planning modules that survived Phase 9J/9K only as testable history.

**Architecture:** Phase 9O is not a behavior expansion. Core and daily smokes are already zero-fallback after 9M/9N, so this slice removes modules with no runtime callers and adds architecture gates that prevent them from returning at the root package. Domain-useful candidate evaluator/reviewer/policy modules stay alive.

**Tech Stack:** Python, pytest via `./scripts/test-backend`, FitMAS smoke harness, fallback census summary.

---

## Files

- Delete: `backend/src/fitmas/planning_snapshot.py`
- Delete: `backend/src/fitmas/adaptation_proposal.py`
- Delete: `backend/src/fitmas/plan_patch_candidate_generator.py`
- Delete: `tests/test_planning_snapshot.py`
- Delete: `tests/test_adaptation_proposal.py`
- Delete: `tests/test_plan_patch_candidate_generator.py`
- Create: `tests/test_phase9o_historical_module_delete_architecture.py`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

## Guardrails

- Do not delete `plan_patch_candidate_evaluator.py`, `plan_patch_candidate_reviewer.py`, or `plan_patch_adaptation_policy.py`; they are still domain-useful.
- Do not add a replacement fallback, prompt, or parser.
- Do not move these modules to `legacy/` unless runtime imports appear during verification.
- Do not edit `conversation_pipeline.py` unless a stale import is found.
- Do not parse free user text; this slice is static cleanup only.

## Tasks

### Task 1: Confirm the modules have no runtime callers

- [x] Run import census:

```bash
rg -n "from fitmas\\.(planning_snapshot|adaptation_proposal|plan_patch_candidate_generator)|import fitmas\\.(planning_snapshot|adaptation_proposal|plan_patch_candidate_generator)" backend/src tests scripts
```

Expected before deletion:

```text
tests/test_planning_snapshot.py
tests/test_adaptation_proposal.py
tests/test_plan_patch_candidate_generator.py
backend/src/fitmas/adaptation_proposal.py
```

Runtime verdict: no runtime caller remains.

### Task 2: Add the failing architecture test

- [x] Create `tests/test_phase9o_historical_module_delete_architecture.py`.
- [x] Assert the three root modules do not exist.
- [x] Assert backend source imports none of the three modules.
- [x] Assert remaining tests do not preserve these historical contracts.
- [x] Run:

```bash
./scripts/test-backend tests/test_phase9o_historical_module_delete_architecture.py -q
```

Expected before deletion: FAIL because the three modules still exist and old tests import them.

### Task 3: Delete the historical modules and their dedicated tests

- [x] Delete the three root modules.
- [x] Delete the three tests that only preserve their historical behavior.
- [x] Run the 9O architecture test again.

Expected after deletion: PASS.

### Task 4: Verify no stale import remains

- [x] Run:

```bash
rg -n "from fitmas\\.(planning_snapshot|adaptation_proposal|plan_patch_candidate_generator)|import fitmas\\.(planning_snapshot|adaptation_proposal|plan_patch_candidate_generator)" backend/src tests scripts
```

Expected after deletion: no output.

### Task 5: Update durable docs

- [x] Add Phase 9O status to `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`.
- [x] Add Phase 9O status to `docs/DECISION-RUNTIME-REFACTOR.md`.
- [x] Add Phase 9O status to `docs/BUILD-ORDER.md`.

Docs must say:

```text
planning_snapshot.py, adaptation_proposal.py, and plan_patch_candidate_generator.py are physically deleted.
The remaining domain-useful evaluator/reviewer/policy modules are intentionally kept.
The next logical slice is extended census beyond core+daily before reducing conversation_decide_bridge or llm/decision_legacy.
```

### Task 6: Verification

- [x] Targeted:

```bash
./scripts/test-backend tests/test_phase9o_historical_module_delete_architecture.py tests/test_phase9j_snapshot_route_delete_architecture.py tests/test_phase9k_adaptation_candidate_flow_delete_architecture.py tests/test_smoke_a_plus_api.py -q
```

- [x] Full backend:

```bash
./scripts/test-backend -q
```

- [x] Core smoke census:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json /tmp/fitmas-9o-core-census.json --timeout 900
```

- [x] Daily smoke census:

```bash
./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json /tmp/fitmas-9o-daily-census.json --timeout 1200
```

- [x] Global summary:

```bash
./scripts/decision-runtime-fallback-census-summary /tmp/fitmas-9o-core-census.json /tmp/fitmas-9o-daily-census.json --json-out /tmp/fitmas-9o-global-summary.json
```

Expected summary:

```text
fallback_scenario_count=0
fallback_turn_count=0
```

- [x] Diff hygiene:

```bash
git diff --check
```

## Acceptance

- The three historical root modules are gone.
- Their dedicated tests are gone.
- Architecture tests prevent the root modules and imports from returning.
- Core+daily smoke census remains zero fallback.
- No behavior route, fallback, prompt, or parser is added.
