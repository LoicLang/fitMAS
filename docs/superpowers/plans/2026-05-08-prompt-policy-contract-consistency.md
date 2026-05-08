---
summary: implementation plan for validating conversation prompt policy to contract consistency
read_when:
  - modifying ConversationPromptPolicy contract wiring
  - adding a conversation intent route
  - rendering prompt contracts into conversation system prompts
---

# Prompt Policy / Contract Consistency

## Goal

Add a narrow consistency layer between conversation prompt policies and the
PromptContract registry.

The registry is already traced, but before rendering any contract text into the
LLM prompt we need stronger guarantees:

- every intent policy points to a known contract;
- terminal policies stay no-tool / no-action;
- planning mutation policies stay the only draft-action route;
- future policy additions are caught by tests before they silently bypass the
  registry.

## Scope

In scope:

- expose the intent prompt policies through a read-only helper;
- add tests that every policy contract resolves through `get_prompt_contract`;
- add tests for the high-risk boundaries:
  - `close_turn` and `casual_chat` are terminal text, no tools, no actions;
  - `plan_negotiation` is draft-action and can emit `PlanPatch`;
  - read-only routes expose no actions.

Out of scope:

- rendering PromptContract fields into the LLM system prompt;
- changing prompt content or snapshots;
- changing context inclusion policies;
- changing tool availability.

## TDD Steps

1. Add tests in `tests/test_conversation_prompt_policy_contracts.py`.
2. Confirm they fail because there is no public policy listing helper.
3. Add `list_conversation_prompt_policies()` to `conversation_prompting.py`.
4. Keep the helper immutable/read-only from callers' perspective.
5. Run focused tests and prompt snapshots.
6. Run backend verification before commit.

## Acceptance

- New policy/contract consistency tests pass.
- Prompt snapshots remain unchanged.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
