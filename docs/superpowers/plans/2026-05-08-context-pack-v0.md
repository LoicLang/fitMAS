---
summary: implementation plan for Prompt Context Phase 2 ContextPack V0
read_when:
  - adding ConversationContextPack
  - refactoring context passed to decide or final_reply
  - separating memory families in prompt context
  - preparing modular prompt rendering
---

# Context Pack V0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce typed context packs that describe what a route may see, without changing runtime prompt behavior yet.

**Architecture:** V0 is a pure domain/context module. It groups existing conversation concepts into explicit buckets: turn scope, temporal context, planning, execution reality, memory, active thread, coach profile, tool budget, and optional grounding. It does not parse free user text and does not mutate DB state.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing FitMAS context and grounding contracts.

---

## Files

- Create: `backend/src/fitmas/context_pack.py`
  - Owns typed context pack dataclasses and lightweight introspection helpers.
- Create: `tests/test_context_pack.py`
  - Unit tests for pack boundaries, memory families, and tool budget declarations.
- Later phase, not this first slice: integrate with `conversation_context.py`, `conversation_pipeline.py`, and `llm_prompt_builder.py`.

## Task 1: Add ContextPack Primitives

**Files:**
- Create: `backend/src/fitmas/context_pack.py`
- Test: `tests/test_context_pack.py`

- [ ] **Step 1: Write failing tests**

```python
from fitmas.context_pack import (
    ActiveThreadContext,
    CoachProfileContext,
    ConversationContextPack,
    ExecutionReality,
    MemoryContext,
    PlanningContext,
    TemporalContext,
    ToolBudget,
    TurnScope,
)


def test_context_pack_exposes_memory_families() -> None:
    pack = ConversationContextPack(
        turn_scope=TurnScope(route="conversation_plan_lookup", intent="plan_lookup", capability="read_only"),
        temporal=TemporalContext(time_context={"today": "2026-05-08"}, temporal_summary="demain = 2026-05-09"),
        planning=PlanningContext(timeline_summary="- Samedi: Footing 40 min"),
        execution=ExecutionReality(execution_summary="Hier repos tenu"),
        memory=MemoryContext(
            durable_profile=("objectif 10 km",),
            working_memory=("tension tibias legere",),
            execution_reality=("repos tenu hier",),
            conversation_frame=("question plan demain",),
        ),
        active_thread=ActiveThreadContext(history_messages=()),
        coach_profile=CoachProfileContext(summary="Style direct"),
        tool_budget=ToolBudget(allowed_tools=("get_plan_window",), tool_choice="auto"),
        grounding=None,
    )

    assert pack.memory.family_names() == (
        "durable_profile",
        "working_memory",
        "execution_reality",
        "conversation_frame",
    )
    assert pack.truth_block_names() == (
        "temporal",
        "planning",
        "execution",
        "memory",
        "active_thread",
        "coach_profile",
        "tool_budget",
    )


def test_tool_budget_defaults_to_no_tools() -> None:
    budget = ToolBudget()

    assert budget.allowed_tools == ()
    assert budget.tool_choice is None
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_pack.py -q
```

Expected: FAIL because `fitmas.context_pack` does not exist.

- [ ] **Step 3: Implement pure dataclasses**

Create frozen, slotted dataclasses:

```python
TurnScope
TemporalContext
PlanningContext
ExecutionReality
MemoryContext
ActiveThreadContext
CoachProfileContext
ToolBudget
ConversationContextPack
```

Keep values generic enough for V0:

```text
summaries as strings
facts/history as tuples
grounding as Any | None
```

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_pack.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/context_pack.py tests/test_context_pack.py
git commit -m "Add conversation context pack primitives"
```

## Task 2: Add Builder From Existing ConversationContextBundle

**Files:**
- Modify: `backend/src/fitmas/context_pack.py`
- Test: `tests/test_context_pack.py`

This task is intentionally separate from Task 1. It may be skipped if the first slice needs to stop after pure primitives.

- [ ] **Step 1: Write failing test**

Add a helper that builds a pack from explicit already-rendered summaries, not raw user text.

- [ ] **Step 2: Verify red**

Run the single test and confirm the helper is missing.

- [ ] **Step 3: Implement helper**

Implement `build_conversation_context_pack(...)` from typed summaries and selected facts.

- [ ] **Step 4: Verify green**

Run context pack tests.

- [ ] **Step 5: Commit**

Commit separately as:

```bash
git commit -m "Build context pack from conversation summaries"
```

## Final Verification For V0 Slice

Run:

```bash
.venv/bin/python -m compileall backend/src/fitmas
git diff --check
.venv/bin/python -m pytest tests/test_context_pack.py tests/test_prompt_contracts.py tests/test_prompt_observability.py -q
```

Expected:

```text
compileall OK
git diff --check no output
targeted tests PASS
```
