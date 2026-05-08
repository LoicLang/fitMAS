---
summary: implementation plan for wiring ContextPack metadata into prompt traces
read_when:
  - wiring ConversationContextPack into prompt builders
  - extending PromptTrace with truth block metadata
  - updating prompt snapshots with context pack information
---

# Context Pack Trace Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ContextPack boundaries observable in prompt traces and snapshots without changing the prompt text or LLM behavior.

**Architecture:** The prompt builder accepts an optional `ConversationContextPack`. When present, it only contributes trace metadata: truth block names and tool budget. Prompt content, system prompt, final replies, and runtime decisions remain unchanged.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing FitMAS prompt builders.

---

## Files

- Modify: `backend/src/fitmas/prompt_observability.py`
  - Adds `truth_block_names` to `PromptTrace`.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Accepts optional `context_pack` and passes pack metadata into traces.
- Modify: `tests/test_prompt_observability.py`
  - Tests trace metadata from explicit `ContextPack`.
- Modify: `tests/test_prompt_snapshots.py`
  - Builds the plan lookup snapshot with a ContextPack.
- Modify: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Updates trace/header metadata only.

## Task 1: Extend PromptTrace Metadata

- [ ] **Step 1: Write failing test**

Add assertions that `PromptTrace` exposes `truth_block_names`.

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py::test_build_prompt_trace_counts_system_and_user_chars -q
```

Expected: FAIL because `truth_block_names` does not exist.

- [ ] **Step 3: Implement metadata field**

Add `truth_block_names: tuple[str, ...] = ()` to `PromptTrace` and optional
`truth_block_names: Sequence[str] = ()` to `build_prompt_trace`.

- [ ] **Step 4: Verify green**

Run prompt observability tests.

## Task 2: Wire ContextPack Into Prompt Builders

- [ ] **Step 1: Write failing test**

Pass a `ConversationContextPack` to `build_layered_conversation_prompt` and
assert:

```python
assert bundle.trace.truth_block_names == pack.truth_block_names()
assert bundle.trace.tool_names == ("get_plan_window",)
```

- [ ] **Step 2: Verify red**

Expected: FAIL because builders do not accept `context_pack`.

- [ ] **Step 3: Implement optional metadata-only parameter**

Add `context_pack: ConversationContextPack | None = None` to both conversation
prompt builders. Use it only for:

```python
tool_names=context_pack.tool_budget.allowed_tools if context_pack else ()
truth_block_names=context_pack.truth_block_names() if context_pack else ()
```

- [ ] **Step 4: Verify green**

Run prompt observability and snapshot tests. Update snapshot metadata only.

## Final Verification

Run:

```bash
.venv/bin/python -m compileall backend/src/fitmas
git diff --check
.venv/bin/python -m pytest tests/test_context_pack.py tests/test_prompt_observability.py tests/test_prompt_snapshots.py tests/test_llm_prompt_builder.py -q
```
