---
summary: implementation plan for extracting the conversation coach voice examples prompt module
read_when:
  - extracting coach voice prompt examples
  - modifying coach_voice few-shots in conversation prompts
  - reducing direct coach_voice injection in llm_prompt_builder.py
---

# Coach Voice Examples Prompt Module

## Goal

Extract the conversation-visible coach voice examples from
`llm_prompt_builder.py` into `conversation_prompt_modules.py`, without changing
the rendered conversation system prompt.

The identity/voice rules already live in `build_identity_voice_system_text()`.
This slice isolates the example pack too, so `_CONVERSATION_SYSTEM_TEXT` keeps
moving toward explicit prompt modules.

## Scope

In scope:

- add `build_coach_voice_examples_system_text()`;
- include `coach_voice.COACH_VOICE_FEW_SHOTS_GOOD`;
- include `coach_voice.COACH_VOICE_FEW_SHOTS_BAD`;
- preserve the blank line between good and bad examples;
- replace direct few-shot interpolation in `_CONVERSATION_SYSTEM_TEXT`;
- keep prompt snapshots unchanged.

Out of scope:

- changing coach voice rules or examples;
- editing `coach_voice.py`;
- changing heartbeat prompts;
- changing final composer or speech guards.

## TDD Steps

1. Add a failing unit test in `tests/test_conversation_prompt_modules.py`.
2. Confirm the test fails because the builder is missing.
3. Implement the builder with the existing good/bad example blocks.
4. Replace the direct interpolation in `llm_prompt_builder.py`.
5. Run prompt snapshots and focused prompt tests.
6. Run backend verification before commit.

## Acceptance

- The new unit test passes.
- `tests/test_prompt_snapshots.py` passes with no snapshot update.
- The backend suite remains green.
- One atomic implementation commit follows the plan commit.
