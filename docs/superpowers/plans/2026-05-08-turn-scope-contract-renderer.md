---
summary: implementation plan for rendering safe turn-scope prompt contract text
read_when:
  - rendering PromptContract fields into prompts
  - adding route-specific conversation system prompt modules
  - preparing contract-aware prompt composition
---

# Turn Scope Contract Renderer

## Goal

Create a pure renderer for the safe subset of `PromptContract` fields.

This prepares route-specific prompts without injecting the renderer into the
conversation LLM yet. The current `decide()` path still expects `CoachDecision`,
while some contract fields already describe the future terminal composer target
(`grounded_final_reply`). Rendering the full contract now would create a
contradictory prompt.

## Scope

In scope:

- add `build_turn_scope_contract_system_text(contract)`;
- render capability, allowed tools, allowed actions, truth blocks, and final
  reply mode;
- explicitly avoid rendering `output_schema` for now;
- keep the renderer pure and unused by runtime composition in this slice;
- add focused tests.

Out of scope:

- injecting the contract block into `_CONVERSATION_SYSTEM_TEXT`;
- changing prompt snapshots;
- changing `PromptContract` values;
- changing `CoachDecision` output behavior.

## TDD Steps

1. Add a failing test in `tests/test_conversation_prompt_modules.py`.
2. Confirm it fails because the renderer is missing.
3. Implement the renderer in `conversation_prompt_modules.py`.
4. Run focused prompt module tests and prompt snapshots.
5. Run backend verification before commit.

## Acceptance

- The renderer test passes.
- Prompt snapshots remain unchanged.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
