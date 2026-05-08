---
summary: implementation plan for extracting the conversation tool workflow prompt module
read_when:
  - extracting tool workflow prompt modules
  - modifying replan_after_constraint workflow prompt rules
  - changing draft tool or suggest_replan_candidates prompt text
---

# Tool Workflow Prompt Module

## Goal

Extract the `Workflow replan_after_constraint` block from
`llm_prompt_builder.py` into `conversation_prompt_modules.py`, without changing
the rendered conversation system prompt.

This is another mechanical step in the prompt/context refactor: move from one
mega-prompt toward explicit prompt modules, while keeping dogfood behavior
stable.

## Scope

In scope:

- add `build_tool_workflow_system_text()`;
- keep the existing workflow text byte-for-byte equivalent in the final prompt;
- add a focused unit test for the new module;
- keep prompt snapshots unchanged.

Out of scope:

- changing tool availability;
- changing `suggest_replan_candidates` behavior;
- changing `draft_*` tool contracts;
- changing `CoachDecision`, `PlanPatch`, or final composer behavior.

## TDD Steps

1. Add a failing test in `tests/test_conversation_prompt_modules.py`:
   - imports `build_tool_workflow_system_text`;
   - asserts the text starts with `Workflow replan_after_constraint:`;
   - asserts it mentions `suggest_replan_candidates`, `draft_move_session`,
     and `validate_week_coherence`;
   - asserts it does not contain action schema or identity text.
2. Run the single new test and confirm it fails because the builder is missing.
3. Implement the builder in `conversation_prompt_modules.py`.
4. Replace the literal workflow block in `_CONVERSATION_SYSTEM_TEXT` with the
   builder call.
5. Run prompt snapshots to prove the rendered prompt did not change.
6. Run focused prompt tests and backend verification.

## Acceptance

- `tests/test_conversation_prompt_modules.py` passes.
- `tests/test_prompt_snapshots.py` passes without snapshot updates.
- Backend test suite remains green.
- One atomic behavior-preserving implementation commit after the plan commit.
