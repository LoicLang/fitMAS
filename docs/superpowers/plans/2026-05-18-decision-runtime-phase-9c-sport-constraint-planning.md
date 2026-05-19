---
summary: implementation plan for Decision Runtime Phase 9C sport-constraint planning coverage
read_when:
  - implementing Phase 9C after replace planning coverage
  - removing sport availability planning fallbacks
  - debugging swim_unavailable_two_weeks or availability-driven plan changes
---

# Decision Runtime Phase 9C Sport Constraint Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move sport-availability adaptation, starting with `swim_unavailable_two_weeks`, from legacy candidate fallback to the canonical planning provider.

**Architecture:** Keep the decision loop canonical: typed `CoachUnderstanding` / `TurnPlan.availability_constraint` becomes a `RequestedPlanChange` with a machine `sport_window` source ref. `ReferenceResolver` resolves the typed window against `CoachContext`, `PlanCandidateBuilder` builds bounded replacement candidates, `SportPolicy` decides pending/block/commit, and `PlanningCommandService` writes or stores pending. No free-text parsing, no CoachDecision planning authority.

**Tech Stack:** Python, pytest, FastAPI smoke harness, Decision Runtime planning domain.

---

### Task 1: Capture Red Tests

**Files:**
- Modify: `tests/test_conversation_canonical_planning_bridge.py`
- Modify: `tests/test_domain_planning_reference_resolver.py`
- Modify: `tests/test_domain_planning_candidate_builder.py`
- Modify: `tests/test_smoke_a_plus_api.py`

- [x] **Step 1: Add a bridge test for sport-window planning**

Expected behavior:

```text
CoachUnderstanding.intent=plan_change
requested_change.kind=remove_optional
availability signal sport=swimming unavailable 2026-05-18 -> 2026-06-01
TurnPlan.planning_action=update_session
=> planning_understanding.requested_change.kind=replace
=> source_ref=sport_window:swimming:2026-05-18:2026-06-01
```

- [x] **Step 2: Add resolver and builder tests**

Expected behavior:

```text
ReferenceResolver parses sport_window machine refs.
PlanCandidateBuilder builds replace_session candidates for matching planned swimming sessions only.
Replacement sport is not swimming.
```

- [x] **Step 3: Add smoke gate expectation**

`swim_unavailable_two_weeks` joins canonical planning provider required scenarios.

### Task 2: Implement Canonical Sport Window

**Files:**
- Modify: `backend/src/fitmas/domain/planning/models.py`
- Modify: `backend/src/fitmas/domain/planning/reference_resolver.py`
- Modify: `backend/src/fitmas/domain/planning/candidate_builder.py`
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`

- [x] **Step 1: Add typed `sport_window` references**

Only accept refs shaped like:

```text
sport_window:<sport_type>:<starts_on>:<ends_on>
```

- [x] **Step 2: Build unavailable-sport replacement candidates**

For each planned, incomplete session whose sport matches the typed window, build a `replace_session` patch with a safe alternative.

- [x] **Step 3: Let canonical planning consume availability sidecars**

Availability signals with `scope=sport`, `availability=unavailable|limited`, `sport_type`, `starts_on`, and `ends_on` are planning sidecars, not legacy blockers, when a sport-window planning change is available.

### Task 3: Preserve Side Effects And Gates

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `scripts/smoke_a_plus_api.py`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`

- [x] **Step 1: Preserve memory command sidecars**

When canonical planning returns before legacy candidate flow, apply typed turn-plan memory commands before recording the turn.

- [x] **Step 2: Run gates**

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_reference_resolver.py tests/test_domain_planning_candidate_builder.py tests/test_smoke_a_plus_api.py -k "sport_window or swim_unavailable or canonical_planning"
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9c-swim-final.db --scenario swim_unavailable_two_weeks --timeout 420
./scripts/smoke-decision-runtime-canonical-planning-default
./scripts/test-backend -q
```

Verified so far:

```text
targeted 9C unit gate -> 36 passed, 53 deselected
swim_unavailable_two_weeks smoke -> planning_runtime_pending_confirmation, canonical handled, memory sidecar applied
avoid_back_to_back smoke -> no_change_composed, no fallback_census
replace_swim_with_bike regression smoke -> planning_runtime_pending_confirmation
canonical planning default smoke -> RESULT: OK (10 check(s))
full backend -> 1399 passed, 11 skipped, 11 subtests passed
```
