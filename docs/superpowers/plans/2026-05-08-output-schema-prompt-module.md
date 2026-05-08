---
summary: implementation plan for extracting the conversation output schema prompt module
read_when:
  - extracting output schema prompt modules
  - modifying CoachDecision JSON schema prompt text
  - changing memory_actions, execution_actions or pending_resolution prompt rules
---

# Output Schema Prompt Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the JSON output schema section of the conversation mega-prompt into a named module without changing rendered prompt text.

**Architecture:** Add `build_output_schema_system_text()` to `conversation_prompt_modules.py`. It owns the `CoachDecision` output contract, structured memory/execution actions, pending resolution rules, PlanPatch JSON example, legacy compat, and final no-markdown instruction.

**Tech Stack:** Python 3.13, plain string builders, pytest prompt snapshots.

---

## Files

- Modify: `backend/src/fitmas/conversation_prompt_modules.py`
  - Adds `build_output_schema_system_text()`.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Uses the new module in `_CONVERSATION_SYSTEM_TEXT`.
- Modify: `tests/test_conversation_prompt_modules.py`
  - Tests output schema module boundaries.
- Existing snapshot: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Must remain unchanged.

## Task 1: Extract Output Schema Module

- [ ] **Step 1: Write failing test**

```python
from fitmas.conversation_prompt_modules import build_output_schema_system_text


def test_output_schema_system_text_contains_json_contract() -> None:
    text = build_output_schema_system_text()

    assert text.startswith("Tu reponds UNIQUEMENT avec un JSON CoachDecision valide.")
    assert "memory_actions: liste optionnelle" in text
    assert "pending_resolution: optionnel" in text
    assert 'plan_patch = {' in text
    assert "Compat temporaire acceptee:" in text
    assert text.endswith("Pas de markdown. Pas de texte autour du JSON.")
    assert "Exemples BONS (voix coach)" not in text
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py::test_output_schema_system_text_contains_json_contract -q
```

Expected: FAIL because the function does not exist.

- [ ] **Step 3: Implement module**

Move the exact rendered output text from `Tu reponds UNIQUEMENT...` through
`Pas de markdown. Pas de texte autour du JSON.` into
`build_output_schema_system_text()`.

Important: inside this plain string module, braces are literal single braces,
not f-string escaped double braces.

- [ ] **Step 4: Compose without changing output**

Replace that same text inside `_CONVERSATION_SYSTEM_TEXT` with:

```python
{build_output_schema_system_text()}
```

- [ ] **Step 5: Verify snapshot unchanged**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: PASS with no snapshot edits.

- [ ] **Step 6: Commit and push**

```bash
git add docs/superpowers/plans/2026-05-08-output-schema-prompt-module.md
git commit -m "Plan output schema prompt extraction"
git push

git add backend/src/fitmas/conversation_prompt_modules.py backend/src/fitmas/llm_prompt_builder.py tests/test_conversation_prompt_modules.py
git commit -m "Extract output schema prompt module"
git push
```
