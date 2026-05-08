---
summary: implementation plan for extracting the conversation identity and voice prompt module
read_when:
  - extracting conversation prompt modules
  - modifying llm_prompt_builder.py system prompt composition
  - changing coach identity or voice prompt text
---

# Identity Voice Prompt Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the identity/voice section of the conversation mega-prompt into a named module without changing the rendered prompt text.

**Architecture:** Create a focused prompt module for stable identity, posture, voice rules, and the `fitmas_message` note. `llm_prompt_builder.py` composes the existing `_CONVERSATION_SYSTEM_TEXT` from that module plus the unchanged legacy decision/action block. This is a structural refactor only.

**Tech Stack:** Python 3.13, plain string builders, pytest prompt snapshots.

---

## Files

- Create: `backend/src/fitmas/conversation_prompt_modules.py`
  - Owns small prompt module builders for conversation system prompt composition.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Imports and uses `build_identity_voice_system_text()`.
- Create: `tests/test_conversation_prompt_modules.py`
  - Verifies the module boundary and key voice content.
- Existing snapshot: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - Must remain unchanged.

## Task 1: Extract Identity Voice Module

- [ ] **Step 1: Write failing tests**

```python
from fitmas import coach_voice
from fitmas.conversation_prompt_modules import build_identity_voice_system_text


def test_identity_voice_system_text_contains_voice_contract() -> None:
    text = build_identity_voice_system_text()

    assert text.startswith("Tu es FitMAS, un coach multisport IA.")
    assert "Posture coach (non-negociable):" in text
    assert coach_voice.COACH_VOICE_RULES in text
    assert "Workflow replan_after_constraint" not in text
    assert text.endswith("Telegram / app.")
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py -q
```

Expected: FAIL because `fitmas.conversation_prompt_modules` does not exist.

- [ ] **Step 3: Implement module**

Create `build_identity_voice_system_text()` with the exact identity/voice text
currently at the top of `_CONVERSATION_SYSTEM_TEXT`.

- [ ] **Step 4: Verify module test green**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py -q
```

Expected: PASS.

## Task 2: Compose Existing Mega-Prompt From Module

- [ ] **Step 1: Replace the duplicated top block**

In `llm_prompt_builder.py`, import `build_identity_voice_system_text` and make
`_CONVERSATION_SYSTEM_TEXT` start with:

```python
_CONVERSATION_SYSTEM_TEXT = f"""\
{build_identity_voice_system_text()}

Workflow replan_after_constraint:
...
"""
```

- [ ] **Step 2: Verify snapshot unchanged**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: PASS without snapshot edits. Any snapshot diff means the refactor
changed the rendered prompt and must be corrected.

- [ ] **Step 3: Verify broader prompt tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py tests/test_prompt_snapshots.py tests/test_llm_prompt_builder.py tests/test_prompt_observability.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/fitmas/conversation_prompt_modules.py backend/src/fitmas/llm_prompt_builder.py tests/test_conversation_prompt_modules.py
git commit -m "Extract identity voice prompt module"
```

## Final Verification

Run:

```bash
.venv/bin/python -m compileall backend/src/fitmas
git diff --check
.venv/bin/python -m pytest tests/test_conversation_prompt_modules.py tests/test_prompt_snapshots.py tests/test_llm_prompt_builder.py tests/test_prompt_observability.py tests/test_prompt_truth_gates.py -q
```
