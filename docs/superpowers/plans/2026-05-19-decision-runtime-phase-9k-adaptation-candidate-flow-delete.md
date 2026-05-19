---
summary: Phase 9K plan for deleting adaptation_candidate_flow from conversation runtime
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9J
  - removing adaptation_candidate_flow or plan_patch_candidate_generator from conversation runtime
  - auditing remaining planning legacy routes
---

# Decision Runtime Phase 9K Adaptation Candidate Flow Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the active `adaptation_candidate_flow` fallback from `conversation_pipeline.py`.

**Architecture:** Canonical planning owns typed plan changes. `conversation_pipeline.py` must no longer call the legacy LLM `plan_patch_candidate_generator`, evaluate its candidates, create pending confirmations from it, or record `adaptation_candidate_flow` census entries. Candidate primitives remain allowed in `domain/planning/*` and pending-choice serialization because they are machine artifacts, not a conversation fallback route.

**Tech Stack:** Python, pytest, FitMAS Decision Runtime, fallback census, smoke API harness.

---

## Tasks

- [x] Add an architecture test forbidding `adaptation_candidate_flow`, `_maybe_handle_plan_adaptation_candidates`, `_should_use_plan_adaptation_candidate_flow`, `generate_plan_patch_candidates`, and `plan_patch_candidate_generator` inside `backend/src/fitmas/conversation_pipeline.py`.
- [x] Run that test and verify it fails against the current runtime.
- [x] Remove the pre-decide and post-decide candidate fallback calls from `conversation_pipeline.py`.
- [x] Remove candidate-flow imports and helper functions that only existed for that fallback.
- [x] Update or delete tests that asserted the old fallback as desired behavior.
- [x] Keep tests for pure candidate modules outside the runtime when still useful.
- [x] Run targeted architecture/core gates.
- [x] Run smoke API planning fallback census for the covered dogfood lanes.
- [x] Run the full backend suite and `git diff --check`.
- [x] Update `BUILD-ORDER`, `DECISION-RUNTIME-REFACTOR`, and `DECISION-RUNTIME-LEGACY-KILL-LIST`.

## Acceptance

- `conversation_pipeline.py` contains no active `adaptation_candidate_flow` route.
- `conversation_pipeline.py` does not import or call `plan_patch_candidate_generator`.
- Covered planning smokes stay `fallback_scenario_count=0`.
- Full backend is green.
