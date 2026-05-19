---
summary: Phase 9F plan for routing broad availability windows through canonical planning
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9E
  - migrating travel or multi-day availability constraints out of planning_snapshot_flow
  - adding typed planning references for broad constraints
---

# Decision Runtime Phase 9F Availability Window Canonical Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans. This slice is safety-sensitive: do not create a broad multi-day mutation until the candidate model can prove it.

**Goal:** Move broad typed availability constraints, such as travel from Wednesday to Friday, out of `planning_snapshot_flow` and into the canonical planning provider.

**Architecture:** The LLM/TurnPlan may provide a typed availability artifact. The backend converts it into `RequestedPlanChange(kind="constraint_window")`, resolves `availability_window:<scope>:<starts_on>:<ends_on>`, and the planning domain returns a canonical block/no-write result until a real multi-day candidate builder exists.

**Non-negotiables:**

- no deterministic parsing of free user text;
- no broad PlanPatch generated directly by the LLM;
- no snapshot/candidate legacy fallback for typed travel windows;
- no DB write from domain planning;
- `ReplyComposer` / planning runtime reply adapter speaks only from the `PlanningDecisionResult`.

## Scope

Supported canonical input:

```text
RequestedPlanChange(
  kind="constraint_window",
  source_ref="availability_window:general:2026-05-20:2026-05-22",
  target_ref=None,
  risk_signals=("availability",),
)
```

Initial behavior:

```text
planning_runtime_block
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
no planning_snapshot_flow
no adaptation_candidate_flow
no event
no pending
```

This is intentionally conservative. A multi-day travel rewrite can touch several sessions and should not be improvised by a fallback compiler.

## Files

Modify:

- `backend/src/fitmas/decision/understanding.py`
  - Add `constraint_window` as a typed requested-change kind.

- `backend/src/fitmas/domain/planning/models.py`
  - Add `availability_window` reference kind and `scope`.

- `backend/src/fitmas/domain/planning/reference_resolver.py`
  - Parse `availability_window:<scope>:<starts_on>:<ends_on>`.

- `backend/src/fitmas/domain/planning/decision_service.py`
  - Return a canonical block for broad windows before evaluator/policy.

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - Convert typed general/time/location availability constraints into `constraint_window`.
  - Keep sport-specific constraints on the existing `sport_window` replacement path.

- `scripts/smoke_a_plus_api.py`
  - Require canonical handling for `trip_constraint`.

Tests:

- canonical bridge builds `constraint_window` from typed TurnPlan/signals;
- resolver accepts typed `availability_window`;
- decision service blocks broad windows before evaluator;
- smoke gate fails `trip_constraint` when canonical provider falls back.

## Out Of Scope

- multi-operation travel candidate generation;
- moving/removing several sessions automatically;
- reply tone polish;
- physical deletion of `planning_snapshot_flow`;
- any keyword/regex detection on user text.

