---
summary: implementation plan for Coach Reliability Refactor slice 0
read_when:
  - implementing coach reliability slice 0
  - removing backend canned replies
  - adding heartbeat read-only speech guards
---

# Coach Reliability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase A dogfood usable by ensuring the backend validates state but does not speak as the coach in normal user-facing replies.

**Architecture:** Add a thin `FinalReplyContext` + LLM composer for blocked/confirmation paths, keep deterministic validation and events, and add a hard heartbeat read-only speech guard. `PlanPatch` remains the action artifact for this slice.

**Tech Stack:** Python 3.13, FastAPI app modules, SQLAlchemy models, pytest/unittest tests, existing `llm_gateway.request_text`.

---

### Task 1: Document Slice 0

**Files:**
- Create: `docs/COACH-RELIABILITY-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [x] **Step 1: Add the reliability refactor doc**

Create `docs/COACH-RELIABILITY-REFACTOR.md` with front matter and the CTO order:
slice 0 final replies, truth source, recheck, tool-loop 3A, heartbeat agency, action-tools later.

- [x] **Step 2: Link it from BUILD-ORDER**

Add a row before Chantier 2:
`0bis | Coach reliability refactor slice 0 | in progress | docs/COACH-RELIABILITY-REFACTOR.md`.

- [x] **Step 3: Verify docs list**

Run: `./scripts/docs:list`

Expected: new doc appears with summary and read_when hints.

### Task 2: Add Final Reply Composer

**Files:**
- Create: `backend/src/fitmas/final_reply.py`
- Test: `tests/test_final_reply.py`

- [x] **Step 1: Write failing tests**

Add tests for:
- composer prompt contains blocked event reason and forbids claiming mutation when no event committed;
- validation rejects old backend templates;
- validation rejects action claims when `allowed_to_claim_mutation=False`;
- outage fallback stays short and non-technical.

- [x] **Step 2: Run tests red**

Run: `./scripts/test-backend tests/test_final_reply.py -q`

Expected: import failure for `fitmas.final_reply`.

- [x] **Step 3: Implement minimal module**

Create:
- `FinalReplyContext`
- `BlockedEvent`
- `build_final_reply_prompt`
- `is_valid_final_reply`
- `compose_final_reply`
- `outage_fallback_reply`

Use `coach_voice` for voice validation and `claim_guard.looks_like_action_claim` for no-commit claims.

- [x] **Step 4: Run tests green**

Run: `./scripts/test-backend tests/test_final_reply.py -q`

Expected: all tests pass.

### Task 3: Route Blocked/Confirmation Replies Through Composer

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_blocked_mutation_reply.py`

- [x] **Step 1: Write failing tests**

Patch `fitmas.conversation_pipeline.final_reply.compose_final_reply` to return a natural phrase and assert:
- `_blocked_plan_patch_reply` returns composer text;
- `_blocked_mutation_reply` returns composer text;
- confirmation prompt no longer contains `Reponds oui ou non`.

- [x] **Step 2: Run tests red**

Run: `./scripts/test-backend tests/test_blocked_mutation_reply.py -q`

Expected: current canned replies fail the new assertions.

- [x] **Step 3: Implement routing**

Import `fitmas.final_reply`.
Build a `FinalReplyContext` from validation/service results.
Call composer first, then `outage_fallback_reply` only if composer fails.

- [x] **Step 4: Run tests green**

Run: `./scripts/test-backend tests/test_blocked_mutation_reply.py -q`

Expected: all tests pass.

### Task 4: Add Heartbeat Read-Only Speech Guard

**Files:**
- Modify: `backend/src/fitmas/coach_voice.py`
- Modify: `backend/src/fitmas/skills/heartbeat/heartbeat.py`
- Test: `tests/test_coach_voice_cross_pipeline.py`
- Test: `tests/test_heartbeat_grounding.py`

- [x] **Step 1: Write failing tests**

Add tests that:
- `coach_voice.message_claims_readonly_commit("On verrouille ca...")` is true;
- `coach_voice.message_claims_readonly_commit("Je te proposerais de verrouiller...")` is false;
- heartbeat `_llm_generate(... pipeline="heartbeat_briefing")` returns `None` for read-only commit claims.

- [x] **Step 2: Run tests red**

Run: `./scripts/test-backend tests/test_coach_voice_cross_pipeline.py tests/test_heartbeat_grounding.py -q`

Expected: missing helper / guard failure.

- [x] **Step 3: Implement guard**

Add `READONLY_COMMIT_CLAIM_PATTERNS` and `message_claims_readonly_commit`.
In `_llm_generate`, if pipeline starts with `heartbeat` and the message claims read-only commit, log and return `None`.

- [x] **Step 4: Run tests green**

Run: `./scripts/test-backend tests/test_coach_voice_cross_pipeline.py tests/test_heartbeat_grounding.py -q`

Expected: all tests pass.

### Task 5: Slice Verification

**Files:**
- Test: `tests/test_final_reply.py`
- Test: `tests/test_blocked_mutation_reply.py`
- Test: `tests/test_coach_voice_cross_pipeline.py`
- Test: `tests/test_heartbeat_grounding.py`
- Test: `tests/test_llm_first_conversation_contract.py`

- [x] **Step 1: Run targeted suite**

Run:
`./scripts/test-backend tests/test_final_reply.py tests/test_blocked_mutation_reply.py tests/test_coach_voice_cross_pipeline.py tests/test_heartbeat_grounding.py tests/test_llm_first_conversation_contract.py -q`

Expected: all targeted tests pass.

- [x] **Step 2: Run relevant conversation suite**

Run:
`./scripts/test-backend tests/test_core_flows.py -q`

Expected: all core flow tests pass or failures are triaged before continuing.
