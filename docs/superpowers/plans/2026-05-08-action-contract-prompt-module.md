---
summary: implementation plan for extracting the conversation action contract prompt module
read_when:
  - extracting action contract prompt modules
  - modifying PlanPatch or CoachDecision prompt rules
  - changing conversation mutation examples
---

# Action Contract Prompt Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the action language section of the conversation mega-prompt into a named module without changing rendered prompt text.

**Architecture:** Add `build_action_contract_system_text()` to `conversation_prompt_modules.py`. It owns the current action choices, planning rules, truth hierarchy rules, no-change factual guidance, and mutation examples. It does not include coach voice few-shots or JSON output schema.

**Tech Stack:** Python 3.13, plain string builders, pytest prompt snapshots.

---

## Files

- Modify: `backend/src/fitmas/conversation_prompt_modules.py`
  - Adds `build_action_contract_system_text()`.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Uses the new module in `_CONVERSATION_SYSTEM_TEXT`.
- Modify: `tests/test_conversation_prompt_modules.py`
  - Tests the action contract module boundary.
- Existing snapshot: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Must remain unchanged.

## Task 1: Extract Action Contract Module

- [ ] **Step 1: Write failing test**

```python
from fitmas.conversation_prompt_modules import build_action_contract_system_text


def test_action_contract_system_text_contains_actions_rules_and_examples() -> None:
    text = build_action_contract_system_text()

    assert text.startswith("Actions possibles:")
    assert '"move_session": move_session = deplacer une seule seance' in text
    assert "respecte cette hierarchie de verite:" in text
    assert "Exemples:" in text
    assert '"ok ca me va" -> no_change' in text
    assert "Exemples BONS (voix coach)" not in text
    assert "Tu reponds UNIQUEMENT" not in text
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py::test_action_contract_system_text_contains_actions_rules_and_examples -q
```

Expected: FAIL because the function does not exist.

- [ ] **Step 3: Implement module**

Move the exact contiguous text from `Actions possibles:` through
`"c'est pas ce qui est sur mon planning dans l'app" -> no_change` into
`build_action_contract_system_text()`.

- [ ] **Step 4: Compose without changing output**

Replace that same text inside `_CONVERSATION_SYSTEM_TEXT` with:

```python
{build_action_contract_system_text()}
```

- [ ] **Step 5: Verify snapshot unchanged**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: PASS with no snapshot edits.

- [ ] **Step 6: Commit and push**

```bash
git add docs/superpowers/plans/2026-05-08-action-contract-prompt-module.md
git commit -m "Plan action contract prompt extraction"
git push

git add backend/src/fitmas/conversation_prompt_modules.py backend/src/fitmas/llm_prompt_builder.py tests/test_conversation_prompt_modules.py
git commit -m "Extract action contract prompt module"
git push
```
