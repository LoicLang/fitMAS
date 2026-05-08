---
summary: implementation plan for injecting safe PromptContract turn scope into conversation system prompts
read_when:
  - injecting PromptContract text into conversation prompts
  - modifying build_conversation_system_text
  - changing llm_prompt_builder.py system prompt selection
---

# Contract-Aware Conversation System Prompt

## Goal

Inject the safe turn-scope contract block into conversation system prompts when
a `ConversationPromptPolicy` has a `contract_name`.

The previous slice split `decision_output_schema` from final `output_schema`,
so the prompt can now say what the current LLM call must return without
contradicting the final composer target.

## Scope

In scope:

- allow `build_conversation_system_text(contract=None)` to include a contract
  block after identity/voice and before broad workflow/action rules;
- resolve `prompt_policy.contract_name` through `get_prompt_contract()`;
- use the contract-aware system text in both classic and layered builders;
- update the plan lookup prompt snapshot;
- keep `output_schema` hidden from the turn-scope block.

Out of scope:

- changing PromptContract values;
- changing which policies select which contracts;
- removing the legacy broad prompt blocks;
- changing final composer routing.

## TDD Steps

1. Add failing tests:
   - composed system text includes the contract block in the right order when a
     contract is passed;
   - layered/classic builders include the plan lookup contract block when the
     plan lookup policy is selected.
2. Implement optional contract composition.
3. Wire `llm_prompt_builder.py` to resolve the policy contract.
4. Run snapshots, update only the expected plan lookup prompt if it changed as
   intended.
5. Run focused prompt tests and backend verification.

## Acceptance

- Contract-aware builder tests pass.
- Snapshot changes only by adding the turn-scope block and trace char counts.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
