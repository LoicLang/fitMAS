---
summary: implementation plan for extracting the conversation calendar truth prompt module
read_when:
  - extracting truth hierarchy prompt modules
  - modifying calendar status semantics in conversation prompts
  - changing adapted vs done prompt rules
---

# Calendar Truth Prompt Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the contiguous calendar truth/status section of the conversation mega-prompt into a named module without changing rendered prompt text.

**Architecture:** Add `build_calendar_truth_system_text()` to `conversation_prompt_modules.py`. It owns the current calendar status semantics: `planned`, `adapted`, `done`, `skipped`, `rest`, and the proof rule for execution. `llm_prompt_builder.py` composes the unchanged system prompt from identity/voice, calendar truth, then the remaining legacy action contract.

**Tech Stack:** Python 3.13, plain string builders, pytest prompt snapshots.

---

## Files

- Modify: `backend/src/fitmas/conversation_prompt_modules.py`
  - Adds `build_calendar_truth_system_text()`.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Uses the new module in `_CONVERSATION_SYSTEM_TEXT`.
- Modify: `tests/test_conversation_prompt_modules.py`
  - Tests the module boundary and key status semantics.
- Existing snapshot: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Must remain unchanged.

## Task 1: Extract Calendar Truth Module

- [ ] **Step 1: Write failing test**

```python
from fitmas.conversation_prompt_modules import build_calendar_truth_system_text


def test_calendar_truth_system_text_contains_status_semantics() -> None:
    text = build_calendar_truth_system_text()

    assert text.startswith("Analyse le message utilisateur")
    assert "`adapted` = seance modifiee/remplacee/deplacee par FitMAS" in text
    assert "ce n'est PAS une preuve d'execution" in text
    assert "Pour dire qu'une seance a ete faite aujourd'hui" in text
    assert "Actions possibles:" not in text
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py::test_calendar_truth_system_text_contains_status_semantics -q
```

Expected: FAIL because the function does not exist.

- [ ] **Step 3: Implement module**

Move the exact contiguous text from `Analyse le message utilisateur...` through
the execution proof rule into `build_calendar_truth_system_text()`.

- [ ] **Step 4: Compose without changing output**

Replace that same text inside `_CONVERSATION_SYSTEM_TEXT` with:

```python
{build_calendar_truth_system_text()}
```

- [ ] **Step 5: Verify snapshot unchanged**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: PASS with no snapshot edits.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/conversation_prompt_modules.py backend/src/fitmas/llm_prompt_builder.py tests/test_conversation_prompt_modules.py
git commit -m "Extract calendar truth prompt module"
```
