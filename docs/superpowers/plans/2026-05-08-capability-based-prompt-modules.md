---
summary: implementation plan for filtering conversation prompt modules by PromptContract capability
read_when:
  - reducing conversation prompt context by capability
  - modifying build_conversation_system_text
  - changing read_only or draft_action prompt modules
---

# Capability-Based Prompt Modules

## Goal

Stop giving read-only conversation routes the mutation-heavy prompt modules.

The previous slices added a safe `Contrat du tour` block. This slice uses that
contract to choose which broad modules are included.

## Scope

In scope:

- keep legacy/no-contract composition unchanged;
- for `read_only` contracts:
  - include identity/voice;
  - include turn-scope contract;
  - include calendar truth;
  - include coach voice examples;
  - include output schema;
  - exclude tool workflow and action contract modules;
- for `draft_action` and write routes, keep the current full module set;
- update prompt snapshot for `conversation_plan_lookup`.

Out of scope:

- rewriting the output schema block;
- removing `CoachDecision` from read-only routes;
- changing final composer routing;
- changing tool budgets.

## TDD Steps

1. Add failing tests in `tests/test_conversation_prompt_modules.py`:
   - read-only contract excludes `Workflow replan_after_constraint` and
     `Actions possibles`;
   - plan negotiation still includes both mutation modules;
   - no-contract composition remains legacy full.
2. Add/adjust builder tests proving plan lookup prompt excludes mutation modules.
3. Implement capability-based module selection in `build_conversation_system_text`.
4. Update the plan lookup snapshot.
5. Run focused prompt tests and backend verification.

## Acceptance

- Read-only prompt snapshot is smaller and lacks mutation modules.
- Draft/action prompts still include mutation modules.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
