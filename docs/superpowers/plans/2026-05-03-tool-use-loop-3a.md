---
summary: implementation plan for Chantier 3A tool-use loop
read_when:
  - implementing Chantier 3 tool-use loop
  - adding validate_plan_patch as a runtime tool
  - changing LLM tool-use round trips or final replies
---

# Tool-Use Loop 3A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the coach LLM read and validate enough truth before deciding, while keeping `PlanPatch` and backend commit/audit as the only write path.

**Architecture:** Add `validate_plan_patch` as a validation-only runtime tool, expand the conversation tool loop to multiple bounded rounds, keep all requested tool ids satisfied, then compose the visible reply after commit/block from machine facts. No native write tools in this slice.

**Tech Stack:** Python 3.13, Pydantic, SQLAlchemy-backed FitMAS services, Anthropic-compatible tool-use gateway, existing smoke scripts.

---

### Task 1: Validation Tool

**Files:**
- Modify: `backend/src/fitmas/tools/contract.py`
- Modify: `backend/src/fitmas/tools/registry.py`
- Test: `tests/test_tool_runtime.py`

- [x] **Step 1: Write failing tests**

Add tests proving `validate_plan_patch` is offered to conversation, returns `valid` for a clean `move_session`, and returns `blocked` plus `suggested_fix` for an occupied target.

- [x] **Step 2: Run red**

Run: `./scripts/test-backend tests/test_tool_runtime.py::ToolRuntimeTest::test_validate_plan_patch_tool_returns_valid_for_clean_move -q`

Expected: fail because the tool is not registered.

- [x] **Step 3: Implement minimal tool**

Extend `ToolContext` with optional `db` and implement `validate_plan_patch` by parsing a `PlanPatch`, calling `validate_plan_patch`, and returning a JSON-safe validation payload.

- [x] **Step 4: Run green**

Run: `./scripts/test-backend tests/test_tool_runtime.py -q`

Expected: all tool runtime tests pass.

### Task 2: Multi-Round Tool Loop

**Files:**
- Modify: `backend/src/fitmas/llm.py`
- Test: `tests/test_llm_tools.py`

- [x] **Step 1: Write failing tests**

Add tests for a second tool round after the first result, total budget blocking, and tool result delivery for every requested id.

- [x] **Step 2: Run red**

Run: `./scripts/test-backend tests/test_llm_tools.py::LLMToolsTest::test_tool_loop_allows_second_round_after_results -q`

Expected: fail because follow-up requests currently do not include `tools=`.

- [x] **Step 3: Implement loop**

Replace the one-followup flow with a bounded loop: max 3 tool rounds, max 6 tool calls total, same tool whitelist on follow-ups, and JSON repair only after the terminal assistant response.

- [x] **Step 4: Run green**

Run: `./scripts/test-backend tests/test_llm_tools.py -q`

Expected: all LLM tool tests pass.

### Task 3: Final Reply After Planning Result

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_final_reply.py`
- Test: `tests/test_blocked_mutation_reply.py`

- [x] **Step 1: Write failing tests**

Add tests proving an applied `PlanPatch` can use `final_reply.compose_final_reply` with committed events, while blocked/confirmation paths still avoid backend templates.

- [x] **Step 2: Implement minimal post-result composition**

Build `FinalReplyContext` from applied events, blocked events or pending summary. Use the existing event summary as outage fallback only.

- [x] **Step 3: Run green**

Run: `./scripts/test-backend tests/test_final_reply.py tests/test_blocked_mutation_reply.py -q`

Expected: all final reply tests pass.

### Task 4: Docs And Real Smokes

**Files:**
- Modify: `docs/RUNTIME-TOOLS.md`
- Modify: `docs/LLM-FIRST-CONVERSATION.md`
- Modify: `docs/BUILD-ORDER.md`

- [x] **Step 1: Update docs**

Document 3A as delivered: validation tool, multi-round read/validation loop, `PlanPatch` kept, native write tools deferred.

- [x] **Step 2: Run verification**

Run:

```bash
./scripts/test-backend -q
./scripts/smoke-real-conversations --scenario info_query --scenario today_unavailability --scenario future_unavailability --scenario compound_non_completion_swap
```

Expected: backend tests pass and smokes do not claim uncommitted mutations.
