---
summary: implementation plan for the terminal close-turn conversation lane
read_when:
  - fixing over-eager Telegram replies on short acknowledgements
  - modifying conversation_turn_planner.py
  - modifying conversation_prompting.py
  - modifying llm_prompt_builder.py
  - modifying conversation_pipeline.py
  - extending final_reply.py for no-action conversation turns
---

# Terminal Close Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development before implementation. This plan is intentionally small enough to execute inline.

**Goal:** Add a terminal conversation lane for social closures like "Okay chef" so FitMAS can close a turn naturally without tools, planning context, or open-question reprompting.

**Architecture:** Keep LLM-first intent detection: the turn planner may classify a user message as `close_turn`. The backend then applies a machine-state policy: no terminal close if a pending confirmation or critical action is active; otherwise bypass the heavy `decide()` path, suppress the open-question marker, offer zero tools, and compose the final visible text through `final_reply.py`.

**Tech Stack:** Python 3.13, FastAPI conversation pipeline, Pydantic turn planner, existing `FinalReplyContext`, pytest/unittest via `./scripts/test-backend`.

---

### Task 1: Turn Intent And Prompt Policy

**Files:**
- Modify: `backend/src/fitmas/conversation_turn_planner.py`
- Modify: `backend/src/fitmas/conversation_prompting.py`
- Modify: `backend/src/fitmas/llm.py`
- Test: `tests/test_conversation_prompting.py`

- [ ] Add `close_turn` to the LLM turn planner contract.
- [ ] Add a `casual_close` prompt policy with minimal context and no open-question marker.
- [ ] Map `close_turn`, `trivial_ack`, and `casual_chat` to that policy.
- [ ] Ensure the conversation tool budget returns zero tools for those terminal/noop social intents.

### Task 2: Open Question Marker Suppression

**Files:**
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
- Test: `tests/test_llm_prompt_builder.py`

- [ ] Add `include_open_question_marker` to `ConversationPromptPolicy`.
- [ ] Gate `_open_question_block()` on that policy field.
- [ ] Verify `casual_close` prompts do not inject `Question ouverte du tour precedent`.
- [ ] Preserve the existing marker behavior for planning/execution policies.

### Task 3: Terminal Composer

**Files:**
- Modify: `backend/src/fitmas/final_reply.py`
- Test: `tests/test_final_reply.py`

- [ ] Add `compose_close_turn_reply()` using the existing final reply composer.
- [ ] Add `is_valid_close_turn_reply()` with stricter validation: no question mark, no action claim, short length, no receipt-style, no voice violation.
- [ ] Add `close_turn_outage_fallback_reply()` as a short non-technical fallback.

### Task 4: Pipeline Branch

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_core_flows.py`

- [ ] Add `_should_use_terminal_close_path()` based on the LLM turn plan and machine state.
- [ ] Before `decide()`, route eligible `close_turn` turns to `compose_close_turn_reply()`.
- [ ] Record `response_mode="close_turn_composed"` and context fields for audit (`terminal_close`, `tools_offered=0`, `open_question_marker="suppressed"`).
- [ ] Do not use this branch when a pending confirmation is active or secondary health/availability/planning/execution signals exist.

### Task 5: Docs And Verification

**Files:**
- Modify: `docs/CONVERSATION.md`
- Modify: `docs/LLM-FIRST-CONVERSATION.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] Document that `close_turn` is a terminal no-action lane, not deterministic text parsing.
- [ ] Run targeted tests:
  `./scripts/test-backend tests/test_conversation_prompting.py tests/test_llm_prompt_builder.py tests/test_final_reply.py tests/test_core_flows.py -q`
- [ ] Run the LLM-first contract tests:
  `./scripts/test-backend tests/test_llm_first_conversation_contract.py -q`
