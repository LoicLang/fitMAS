---
summary: implementation plan for moving conversation system prompt composition into prompt modules
read_when:
  - composing conversation system prompts
  - modifying llm_prompt_builder.py system prompt wiring
  - adding or reordering conversation prompt modules
---

# Conversation System Prompt Composition

## Goal

Move the final composition of the conversation system prompt from
`llm_prompt_builder.py` into `conversation_prompt_modules.py`.

The previous slices extracted the prompt blocks. This slice makes the module
own the assembly order too, so `llm_prompt_builder.py` can focus on runtime
prompt bundling instead of carrying prompt text structure.

## Scope

In scope:

- add `build_conversation_system_text()`;
- compose the existing modules in the current order;
- replace `_CONVERSATION_SYSTEM_TEXT` with a direct builder call;
- preserve the rendered prompt exactly;
- add a focused test for ordering and content.

Out of scope:

- changing prompt content;
- changing prompt order;
- changing prompt policies, ContextPack, or trace metadata;
- changing heartbeat prompts.

## TDD Steps

1. Add a failing test that imports `build_conversation_system_text()`.
2. Assert the composed text contains the six modules in order:
   identity/voice, tool workflow, calendar truth, action contract, voice
   examples, output schema.
3. Confirm the test fails because the builder is missing.
4. Implement the builder by composing existing module builders.
5. Replace `_CONVERSATION_SYSTEM_TEXT = f"""..."""` with
   `_CONVERSATION_SYSTEM_TEXT = build_conversation_system_text()`.
6. Run snapshots to confirm no rendered prompt drift.
7. Run focused prompt tests and backend verification.

## Acceptance

- The new composition test passes.
- Prompt snapshot remains unchanged.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
