---
summary: implementation plan for Decision Runtime Phase 8V planning fallback reduction
read_when:
  - implementing Decision Runtime Phase 8V
  - reducing canonical planning fallback to legacy decide
  - debugging date-based planning refs in CoachUnderstanding
---

# Decision Runtime Phase 8V Planning Fallback Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce legacy planning fallback for typed date/day planning references that the backend can resolve unambiguously against `ScheduledSession`.

**Architecture:** Keep LLM-first understanding and deterministic backend resolution. The LLM may emit typed refs like `day:wednesday` or `date:2026-05-20`; `ReferenceResolver` resolves those machine artifacts against DB truth and promotes a date ref to a session ref only when exactly one planned session exists on that date. No free user text parsing is added.

**Tech Stack:** Python dataclasses, existing planning domain modules, pytest through `./scripts/test-backend`, real API/LLM smoke wrappers.

**Status 2026-05-17:** delivered. Scope expanded after the real smoke found two production-shaped gaps: read-only could absorb a `plan_mutation` misclassified as `general_answer`, and Understanding could emit a correct `plan_change` with non-machine refs while TurnPlan already carried typed weekday refs.

Durable rule added: Understanding remains first, but the planning provider may use typed TurnPlan refs when the Understanding artifact is not provider-usable and no strong command signal would be lost.

---

### Task 1: Date Refs Resolve To Sessions

**Files:**
- Modify: `backend/src/fitmas/domain/planning/reference_resolver.py`
- Test: `tests/test_domain_planning_reference_resolver.py`

- [x] **Step 1: Write failing tests**

Add tests proving:

```python
def test_resolver_promotes_swap_date_refs_to_sessions_when_unambiguous() -> None:
    requested = RequestedPlanChange(
        kind="swap",
        source_ref="date:2026-05-20",
        target_ref="date:2026-05-21",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="swap days",
        risk_signals=(),
    )

    resolved = ReferenceResolver(
        _context(_session(1, "2026-05-20"), _session(2, "2026-05-21"))
    ).resolve(requested)

    assert resolved.source.kind == "session"
    assert resolved.source.session_id == 1
    assert resolved.target.kind == "session"
    assert resolved.target.session_id == 2
    assert resolved.warnings == ()
```

```python
def test_resolver_keeps_ambiguous_date_source_unresolved() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="date:2026-05-20",
        target_ref="date:2026-05-22",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="move day",
        risk_signals=(),
    )

    resolved = ReferenceResolver(
        _context(_session(1, "2026-05-20"), _session(2, "2026-05-20"))
    ).resolve(requested)

    assert resolved.source.kind == "date"
    assert "unresolved_source_ref" in resolved.warnings
```

- [x] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_reference_resolver.py::test_resolver_promotes_swap_date_refs_to_sessions_when_unambiguous tests/test_domain_planning_reference_resolver.py::test_resolver_keeps_ambiguous_date_source_unresolved
```

Expected: both fail because resolver currently leaves date refs as date refs.

- [x] **Step 3: Implement resolver promotion**

In `ReferenceResolver.resolve()`, parse refs, then promote source/target date refs for roles that require sessions:

```text
move/lighten/replace: source must resolve to one session
swap: source and target must resolve to one session each
create: target remains a date
```

Warnings must reflect role mismatch. Do not parse user text.

- [x] **Step 4: Verify green**

Run the same two tests and the full resolver test file.

### Task 2: Canonical Provider Gate Accepts Date-Based Session Roles

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [x] **Step 1: Write failing tests**

Add tests proving date/day refs can enter the canonical provider for:

```text
swap date/date
move date/date
lighten date
replace date
```

- [x] **Step 2: Verify red**

Run the new tests. Expected: fail while the gate requires session refs.

- [x] **Step 3: Implement gate expansion**

Allow date-like refs in source positions when the planning domain can resolve them. Keep free text rejected.

- [x] **Step 4: Verify green**

Run the bridge test file.

### Task 3: Smoke Proves Swap By Day Avoids Legacy Decide

**Files:**
- Modify: `scripts/smoke_a_plus_api.py`
- Modify: `tests/test_smoke_a_plus_api.py`

- [x] **Step 1: Write failing smoke evaluator test**

Add `swap_by_day` to required canonical planning provider scenarios and add a fixture where `swap_by_day` writes pending without canonical trace. It must fail with:

```text
canonical planning provider did not handle supported planning turn
```

- [x] **Step 2: Verify red**

Run the new smoke evaluator test. Expected: fail until the scenario is listed.

- [x] **Step 3: Implement smoke requirement**

Add `swap_by_day` to `_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS`.

- [x] **Step 4: Verify green**

Run `tests/test_smoke_a_plus_api.py`.

### Task 3bis: Read-Only Guard And TurnPlan Swap Bridge

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_conversation_canonical_readonly_bridge.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [x] **Step 1: Keep read-only out of planning turns**

Reject canonical read-only whenever `turn_plan.primary_intent` is non-read-only, including `plan_mutation`.

- [x] **Step 2: Add typed TurnPlan swap recovery**

Add `planning_understanding_for_provider()` so `planning_action="swap_sessions"` plus typed temporal refs can produce a `RequestedPlanChange(kind="swap")` when the Understanding artifact is not provider-usable.

- [x] **Step 3: Separate weak sidecars from real commands**

Weak planning sidecars no longer block the provider:

```text
record_preference scope day/week/general/session/planning/plan
record_availability available/unknown without starts_on/ends_on/sport_type
```

Durable commands still block, for example unavailable sport/date constraints.

### Task 4: Docs And Verification

**Files:**
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [x] **Step 1: Update docs**

Document Phase 8V as delivered:

```text
date/day typed refs can resolve to ScheduledSession when unambiguous
swap_by_day is now a required canonical planning smoke scenario
fallback legacy planning remains only for unsupported or ambiguous refs
```

- [x] **Step 2: Run verification**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_reference_resolver.py tests/test_conversation_canonical_planning_bridge.py tests/test_smoke_a_plus_api.py tests/test_phase8t_canonical_planning_provider_architecture.py
./scripts/smoke-decision-runtime-canonical-planning-default
./scripts/test-backend -q
git diff --check
```

Delivered verification:

```bash
./scripts/test-backend -q tests/test_domain_planning_reference_resolver.py tests/test_domain_planning_decision_service.py::test_decide_plan_change_builds_swap_from_date_refs tests/test_conversation_canonical_planning_bridge.py tests/test_conversation_canonical_readonly_bridge.py tests/test_smoke_a_plus_api.py::test_default_planning_provider_requires_canonical_trace_for_swap_by_day
# 33 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario swap_by_day --timeout 420 --keep-db --db-path .tmp-8v-swap-4.db
# RESULT: OK (1 check)

./scripts/smoke-decision-runtime-canonical-planning-default
# RESULT: OK (9 checks)
```
