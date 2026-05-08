---
summary: implementation plan for Prompt Context Phase 1 PromptContract registry
read_when:
  - adding PromptContract definitions
  - wiring prompt contracts into conversation traces
  - modifying conversation_prompting.py
  - extending prompt snapshots with contract metadata
---

# Prompt Contract Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Declare explicit LLM capabilities per conversation route without changing prompt behavior yet.

**Architecture:** Phase 1 adds a read-only PromptContract registry beside existing prompt policies. `ConversationPromptPolicy` still controls context inclusion; `PromptContract` declares capability, tools, actions, truth blocks, output schema, and final reply mode for observability and later prompt modularization.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing FitMAS conversation prompt builders.

---

## Files

- Create: `backend/src/fitmas/prompt_contracts.py`
  - Owns `PromptContract`, route constants, and lookup helpers.
- Modify: `backend/src/fitmas/conversation_prompting.py`
  - Adds optional `contract_name` to `ConversationPromptPolicy`.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Passes the selected contract name into `PromptTrace`.
- Modify: `tests/test_prompt_observability.py`
  - Proves prompt bundle traces expose the contract.
- Create: `tests/test_prompt_contracts.py`
  - Unit tests for the registry contract boundaries.
- Modify: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Updates the baseline trace from `contract: none` to the read-only plan lookup contract.

## Task 1: Add PromptContract Registry

**Files:**
- Create: `backend/src/fitmas/prompt_contracts.py`
- Test: `tests/test_prompt_contracts.py`

- [ ] **Step 1: Write failing tests**

```python
from fitmas.prompt_contracts import get_prompt_contract


def test_plan_lookup_contract_is_read_only() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    assert contract.name == "conversation_plan_lookup"
    assert contract.capability == "read_only"
    assert contract.allowed_actions == ()
    assert contract.output_schema == "grounded_final_reply"
    assert contract.final_reply_mode == "terminal_composer"
    assert "temporal" in contract.required_truth_blocks
    assert "plan_window" in contract.required_truth_blocks


def test_plan_negotiation_contract_can_draft_plan_patch() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    assert contract.capability == "draft_action"
    assert "PlanPatch" in contract.allowed_actions
    assert contract.output_schema == "CoachDecision"
    assert contract.final_reply_mode == "post_runtime"


def test_close_turn_contract_is_terminal_text() -> None:
    contract = get_prompt_contract("conversation_close_turn")

    assert contract.capability == "terminal_text"
    assert contract.allowed_tools == ()
    assert contract.allowed_actions == ()
    assert contract.output_schema == "final_text"
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_contracts.py -q
```

Expected: FAIL because `fitmas.prompt_contracts` does not exist.

- [ ] **Step 3: Implement minimal registry**

Create `PromptContract` with these fields:

```python
name: str
capability: str
allowed_tools: tuple[str, ...]
allowed_actions: tuple[str, ...]
required_truth_blocks: tuple[str, ...]
optional_truth_blocks: tuple[str, ...]
output_schema: str
final_reply_mode: str
max_context_blocks: tuple[str, ...]
```

Add at least:

```text
conversation_close_turn
conversation_casual_chat
conversation_plan_lookup
conversation_execution_report
conversation_plan_negotiation
conversation_health_signal
conversation_generic_question
```

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/prompt_contracts.py tests/test_prompt_contracts.py
git commit -m "Add prompt contract registry"
```

## Task 2: Attach Contracts To Conversation Prompt Traces

**Files:**
- Modify: `backend/src/fitmas/conversation_prompting.py`
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
- Test: `tests/test_prompt_observability.py`
- Snapshot: `tests/snapshots/prompts/conversation_plan_lookup.txt`

- [ ] **Step 1: Write failing test**

Extend `test_layered_prompt_bundle_exposes_trace_metadata`:

```python
assert bundle.trace.prompt_contract == "conversation_plan_lookup"
```

Expected: FAIL because `prompt_contract` is still `None`.

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py::test_layered_prompt_bundle_exposes_trace_metadata -q
```

Expected: FAIL on `prompt_contract`.

- [ ] **Step 3: Add `contract_name` to policies**

Add `contract_name: str | None = None` to `ConversationPromptPolicy`.
Populate each known intent policy with the matching registry name:

```text
CLOSE_TURN -> conversation_close_turn
CASUAL_CHAT -> conversation_casual_chat
EXECUTION_REPORT -> conversation_execution_report
PLAN_NEGOTIATION -> conversation_plan_negotiation
PLAN_LOOKUP -> conversation_plan_lookup
LOAD_REVIEW -> conversation_load_review
FACT_RECALL -> conversation_fact_recall
GENERIC_QUESTION -> conversation_generic_question
```

The default legacy policy can keep `contract_name=None` until its route is explicit.

- [ ] **Step 4: Pass policy contract into traces**

In both conversation prompt builders, pass:

```python
prompt_contract=prompt_policy.contract_name
```

- [ ] **Step 5: Verify green and update snapshot**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py tests/test_prompt_snapshots.py -q
```

Expected first run may fail only because the snapshot trace changed. Update the snapshot to the new trace, then rerun until PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/conversation_prompting.py backend/src/fitmas/llm_prompt_builder.py tests/test_prompt_observability.py tests/snapshots/prompts/conversation_plan_lookup.txt
git commit -m "Trace conversation prompt contracts"
```

## Final Verification For Phase 1 Slice

Run:

```bash
.venv/bin/python -m compileall backend/src/fitmas
git diff --check
.venv/bin/python -m pytest tests/test_prompt_contracts.py tests/test_prompt_observability.py tests/test_prompt_snapshots.py tests/test_conversation_prompting.py tests/test_llm_prompt_builder.py tests/test_prompt_truth_gates.py -q
./scripts/test-backend -q
```

Expected:

```text
compileall OK
git diff --check no output
targeted tests PASS
backend PASS
```
