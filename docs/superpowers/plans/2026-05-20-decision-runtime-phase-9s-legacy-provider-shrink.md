---
summary: Phase 9S plan to audit and shrink the remaining legacy CoachDecision provider
read_when:
  - continuing Decision Runtime cleanup after strict zero fallback census
  - deciding whether legacy decide provider can be reduced
  - reducing conversation_pipeline legacy authority before reply-quality work
---

# Decision Runtime Phase 9S Legacy Provider Shrink Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the runtime smaller by proving where the legacy `CoachDecision` provider is still callable, blocking it from covered canonical lanes, then shrinking the remaining bridge/provider surface.

**Architecture:** This is not a feature-completion slice. It is a deletion and authority-reduction slice. The 62-scenario strict census is zero fallback, so the next job is to remove broad legacy authority without creating new routes, prompts, guards, or deterministic user-text parsing.

**Current evidence:**

```text
strict core + daily + extended:
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0

current provider surface:
backend/src/fitmas/legacy/conversation_decide_bridge.py 158 lines
backend/src/fitmas/llm/decision_legacy.py              556 lines
backend/src/fitmas/conversation_pipeline.py           1918 lines
```

**Delivered status 2026-05-20:**

```text
targeted 9S gate:
123 passed

full backend:
1441 passed, 11 skipped, 11 subtests passed

strict core + daily + extended:
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

Implementation note: `fallback_legacy` remains a measured compatibility result.
The hard block is explicit via `deny_legacy_provider=True`, so old unmigrated
compat tests can still exercise `CoachDecision` while covered canonical lanes
can opt out by construction.

## Why This Is The Right Next Move

The previous slices proved that covered dogfood lanes no longer need `CoachDecision` as fallback. That is not the same as proving the provider can be deleted globally. The right move is therefore:

```text
caller graph -> hard deny covered lanes -> shrink bridge -> quarantine provider -> rerun strict smoke
```

Trade-off:

- safer than deleting `decision_legacy.py` immediately;
- more aggressive than merely documenting the legacy debt;
- keeps focus on the mantra: **not a more complete refactor, a smaller runtime**.

## Non-Negotiables

- Do not add a new prompt.
- Do not add smoke examples to prompts.
- Do not parse free user text deterministically.
- Do not add a new fallback path.
- Do not polish reply quality in this slice.
- Do not broaden `conversation_pipeline.py`.
- Do not delete provider code until import/caller tests prove the deletion lane.

## Scope

### In Scope

- Add a provider caller audit test.
- Add architecture gates that classify remaining legal imports/calls.
- Prevent covered canonical lanes from invoking `run_legacy_coach_decision`.
- Shrink `conversation_decide_bridge.py` if a branch is now provably dead.
- Quarantine `llm/decision_legacy.py` as compatibility provider only.
- Update docs with what remains legacy and why.
- Re-run strict fallback census.

### Out Of Scope

- Reply-quality cleanup (`sport=course`, third-person summaries, generic planning explanations).
- Phase B progression/prescription.
- Full physical deletion of all `legacy_*` LLM modules.
- Rewriting `conversation_pipeline.py` end to end.

## Files

Likely modify:

- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- `backend/src/fitmas/legacy/coach_decision_provider.py`
- `backend/src/fitmas/llm/decision_legacy.py`
- `backend/src/fitmas/decision/fallback_census.py`
- `tests/test_phase9s_legacy_provider_shrink_architecture.py`
- `tests/test_conversation_decide_bridge.py`
- `tests/test_core_flows.py`
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/BUILD-ORDER.md`

Do not modify unless a test proves necessity:

- prompt files;
- `tools/registry.py`;
- planning candidate/evaluator/policy modules;
- heartbeat runtime;
- app routes.

## Tasks

### Task 1: Add caller audit gates

- [x] Create `tests/test_phase9s_legacy_provider_shrink_architecture.py`.
- [x] Assert `run_legacy_coach_decision(` is called only from `conversation_pipeline.py` and tests.
- [x] Assert direct imports of `fitmas.llm.decision_legacy.decide` are not allowed outside legacy provider compatibility.
- [x] Assert `conversation_pipeline.py` routes canonical understanding/read-only/planning/clarification before the legacy provider.
- [x] Assert no covered provider bridge imports `decision_legacy` directly.

Expected first run: fail only where the current graph is too permissive.

### Task 2: Add an explicit provider authority gate

- [x] Introduce one small typed helper, in `legacy/conversation_decide_bridge.py`:

```python
def legacy_provider_allowed_for_turn(turn_context: dict[str, object]) -> bool:
    ...
```

- [x] The helper inspects runtime artifacts only:
  - `canonical_understanding`;
  - `canonical_readonly_reply`;
  - `canonical_planning_provider`;
  - `canonical_pending_provider`;
  - `canonical_clarification`;
  - `turn_plan` payload already stored in context.
- [x] It does not inspect or parse `user_text`.
- [x] Covered canonical lanes return `False` when they mark `deny_legacy_provider=True` or have already handled/blocked.
- [x] Truly unsupported or not-yet-prepared lanes can still return `True`, and remain classified in `fallback_census` if they call the provider.

Purpose:

```text
legacy provider becomes opt-in by runtime state,
not the default sink after every canonical miss.
```

### Task 3: Wire the gate before `run_legacy_coach_decision`

- [x] In `conversation_pipeline.py`, before calling `run_legacy_coach_decision`, check the helper.
- [x] If denied, produce a canonical no-write clarification outcome through `DecisionOutcome` + `ReplyComposer`.
- [x] Record `turn_context["legacy_decide"] = {"legacy_skipped": True, "reason": ...}`.
- [x] Do not call `dependencies.decide`.
- [x] Do not introduce a new prompt or provider call.

Acceptance for this task:

```text
covered canonical lanes cannot reach the provider even if a future branch forgets to set outcome.
```

### Task 4: Shrink `conversation_decide_bridge.py`

- [x] Keep request building only for the remaining provider compatibility path.
- [x] Keep trace/fallback census explicit.
- [x] Update `tests/test_conversation_decide_bridge.py` to test:
  - allowed unknown lane records fallback census;
  - denied canonical planning lane skips provider;
  - denied pending lane skips provider;
  - denied read-only lane skips provider.
- [x] Add a regression test that classified `fallback_legacy` stays allowed unless a canonical bridge sets `deny_legacy_provider=True`.

Target:

```text
conversation_decide_bridge.py should become a narrow compatibility adapter,
not a broad runtime decision path.
```

### Task 5: Quarantine `llm/decision_legacy.py`

- [x] Add architecture tests proving `decision_legacy.decide` is not directly imported outside package compatibility.
- [x] Keep public package compatibility for old tests/imports required by `fitmas.llm.__init__`.
- [x] Mark the module as legacy provider compatibility in its module docstring.
- [x] Do not move or delete support modules until caller graph says they are dead.
- [x] Record remaining public shims:
  - onboarding;
  - fact memory;
  - summaries;
  - parser/model compatibility.

Possible follow-up after 9S, not inside 9S:

```text
split non-conversation helpers out of fitmas.llm compatibility,
then delete conversation decide provider.
```

### Task 6: Documentation update

- [x] Update `docs/DECISION-RUNTIME-REFACTOR.md`.
- [x] Update `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`.
- [x] Update `docs/BUILD-ORDER.md`.

Docs must answer:

```text
What can still call the provider?
Which canonical lanes are hard-denied?
Which files remain legacy but non-authoritative?
What is the next deletion candidate?
```

### Task 7: Verification

Run targeted first:

```bash
./scripts/test-backend \
  tests/test_phase9s_legacy_provider_shrink_architecture.py \
  tests/test_conversation_decide_bridge.py \
  tests/test_core_flows.py -q
```

Then full gates:

```bash
./scripts/test-backend -q
./scripts/smoke-decision-runtime-extended-census
git diff --check
```

Expected smoke result:

```text
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

## Acceptance

- `legacy_decide` remains zero on strict core + daily + extended.
- Covered canonical lanes cannot call the legacy provider by construction.
- Any remaining provider call is classified, audited, and outside covered lanes.
- `conversation_pipeline.py` does not grow materially.
- `conversation_decide_bridge.py` has less authority than before.
- `llm/decision_legacy.py` is quarantined as compatibility, not active product runtime.
- No new prompt bloat.
- No new deterministic parsing of free user text.

## What This Does Not Solve

This slice will not make every reply beautiful. It should make the runtime smaller and harder to bypass. After 9S, the next likely slice is reply quality through the existing `ReplyComposer`, not another provider fallback cleanup.
