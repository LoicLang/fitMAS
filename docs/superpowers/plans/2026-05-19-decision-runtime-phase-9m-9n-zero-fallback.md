---
summary: Phase 9M/9N plan to remove the last global Decision Runtime fallback census entries
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9L
  - removing canonical planning provider fallbacks
  - routing short clarification turns without legacy decide
---

# Decision Runtime Phase 9M/9N Zero Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the four remaining global smoke fallbacks from Phase 9L without adding prompt bloat or deterministic free-text understanding.

**Architecture:** Keep the LLM as the only free-text interpreter. Deterministic code may only normalize typed `CoachUnderstanding`, `RequestedPlanChange`, `ConversationTurnPlan`, and DB-backed refs. Unsupported canonical planning turns must return a canonical block/clarification outcome instead of falling through to `CoachDecision`.

**Tech Stack:** Python, pytest, FitMAS Decision Runtime, canonical planning bridge, smoke fallback census.

---

## Tasks

- [x] Add failing tests for typed swap ref normalization, planning sidecar signals, unsupported planning clarification, and short-slot clarification.
- [x] Normalize typed session refs emitted in `RequestedPlanChange` without parsing raw user text.
- [x] Route unsupported canonical planning changes to a canonical no-write outcome instead of legacy fallback.
- [x] Route `needs_clarification` short turns through a canonical clarification composer before legacy decide.
- [x] Run targeted tests and the core+daily smoke census without `--allow-fallbacks`.
- [x] Update refactor docs and legacy kill list with the new zero-fallback status.
- [x] Run full backend and `git diff --check`.

## Acceptance

- `swap_key_and_recovery`, `lighten_key_after_fatigue`, and `ambiguous_move` no longer emit planning fallback census entries.
- `short_slot_preference` no longer calls `legacy_decide`.
- Combined core+daily fallback census exits zero without `--allow-fallbacks`.
- No new regex or keyword rule is applied to raw user text.
- No new long prompt or test-specific prompt example is added.
