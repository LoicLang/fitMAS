---
summary: implementation plan for Decision Runtime Phase 8G pending resolution extraction
read_when:
  - implementing Decision Runtime Phase 8G
  - moving pending_resolution out of conversation_pipeline.py
  - cutting CoachDecision pending authority toward canonical CoachUnderstanding
  - modifying pending confirmations or plan_patch_choice confirmation handling
---

# Decision Runtime Phase 8G Pending Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move pending confirmation resolution out of `conversation_pipeline.py`, keep behavior stable, and prepare canonical `CoachUnderstanding.pending_resolution` as the future source of truth behind an explicit flag.

**Architecture:** 8G is a legacy extraction slice. The conversation orchestrator must delegate pending application, recheck, accept/reject/ignore/modify handling, and pending keep/supersede bookkeeping to a single bridge. The bridge consumes typed artifacts only. It must never parse free user text deterministically.

**Tech Stack:** Python 3.13, dataclasses, pytest/unittest, existing `PendingMutationConfirmation`, `PlanPatch`, `PlanMutationService`, canonical `CoachUnderstanding`.

---

## CTO Decision

Do **not** delete `CoachDecision.pending_resolution` in 8G.

It remains provider compatibility while canonical Understanding runs in shadow. The useful cut is narrower:

```text
CoachDecision.pending_resolution
or CoachUnderstanding.pending_resolution under flag
  -> PendingResolutionArtifact
  -> ConversationPendingBridge
  -> PlanMutationService / repository pending status
  -> ConversationTurnOutcome
```

This removes pending authority from the mega-orchestrator without forcing a risky provider swap.

## Scope

8G includes:

```text
1. Create `legacy/conversation_pending_bridge.py`.
2. Move pending resolution application out of `conversation_pipeline.py`.
3. Move pending accept recheck out of `conversation_pipeline.py`.
4. Move pending accept for `plan_patch` and `plan_patch_choice` out of `conversation_pipeline.py`.
5. Move keep/supersede pending bookkeeping out of `conversation_pipeline.py`.
6. Add `FITMAS_PENDING_FROM_UNDERSTANDING`, off by default.
7. Add tests proving canonical Understanding can drive pending when the flag is enabled.
8. Add architecture tests so the old helpers do not return to `conversation_pipeline.py`.
```

8G does **not** include:

```text
1. Removing `CoachDecision`.
2. Removing legacy prompt modules.
3. Rewriting visible pending replies through the canonical Reply prompt.
4. Moving all PlanPatch candidate flow writes into `PlanningCommandService`.
5. Deleting `final_reply.py`.
```

Pending visible speech can remain legacy-compatible inside the pending bridge for this slice. The next cleanup can route reject/ignore/clarification replies through `ReplyComposer`.

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. Recheck may call the LLM with a narrow JSON contract; it must not regex the user text.
3. decision/ stays pure.
4. conversation_pipeline.py must not define pending resolution application helpers.
5. conversation_pipeline.py must not call `decision.pending_resolution` directly.
6. Plan writes still go through `apply_patch_for_user` / PlanMutationService.
7. Pending status writes stay centralized in the pending bridge.
8. Canonical Understanding pending is opt-in in 8G.
9. Behavior remains stable with the new flag off.
10. Architecture docs list the remaining legacy debt explicitly.
```

## Flag

```text
FITMAS_PENDING_FROM_UNDERSTANDING
  default: off
  effect: use `CoachUnderstanding.pending_resolution` when present.
          fallback to `CoachDecision.pending_resolution` otherwise.
```

This flag is useful only when `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1` produced a canonical understanding for the turn.

## File Map

Create:

```text
backend/src/fitmas/legacy/conversation_pending_bridge.py
tests/test_phase8g_pending_resolution_architecture.py
tests/test_conversation_pending_bridge.py
```

Modify:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/legacy/conversation_command_bridge.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify unless a failing test proves it necessary:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/tools/registry.py
```

## Target Flow

```text
conversation_pipeline.py
  -> conversation_pending_bridge.apply_pending_resolution(...)
      -> pending_resolution_from_sources(...)
      -> verify_pending_accept_resolution(...)
      -> accept_pending_confirmation(...)
      -> apply_patch_for_user(...)
      -> ConversationTurnOutcome

conversation_pipeline.py
  -> conversation_pending_bridge.keep_pending_for_non_mutating_turn(...)
  -> conversation_pending_bridge.supersede_pending_if_replaced(...)
```

When the canonical flag is enabled:

```text
CoachUnderstanding.pending_resolution
  -> PendingResolutionArtifact(source="coach_understanding")
  -> same pending bridge
```

## Tasks

- [x] Add Phase 8G architecture tests.
- [x] Add pending bridge behavior tests for legacy pending source.
- [x] Add pending bridge behavior test for canonical Understanding source under flag.
- [x] Implement `conversation_pending_bridge.py`.
- [x] Wire `conversation_pipeline.py` to the bridge.
- [x] Update legacy command metrics so `pending_resolution_per_turn` can count canonical pending.
- [x] Update docs and kill list.
- [x] Run targeted pending tests, Phase 8 architecture tests, then full backend tests.

## Acceptance

```text
conversation_pipeline.py no longer defines:
- _apply_pending_resolution
- _verify_pending_accept_resolution
- _accept_pending_confirmation
- _accept_pending_plan_patch_choice

conversation_pipeline.py no longer reads:
- decision.pending_resolution

legacy/conversation_pending_bridge.py owns:
- apply_pending_resolution
- verify_pending_accept_resolution
- accept_pending_confirmation
- keep_pending_for_non_mutating_turn
- supersede_pending_if_replaced

Tests prove:
- accept applies a pending PlanPatch only after typed pending + recheck.
- weak accept keeps pending open.
- reject resolves pending as rejected.
- modify/ignore keep pending open.
- plan_patch_choice selected candidate applies the selected patch.
- canonical Understanding pending works only when flag enabled.
- no regex / keyword parsing on free user text is introduced.
```
