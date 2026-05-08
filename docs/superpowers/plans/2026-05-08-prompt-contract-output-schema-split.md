---
summary: implementation plan for splitting prompt contract decision and final output schemas
read_when:
  - modifying PromptContract output schema fields
  - rendering turn-scope contracts into prompts
  - resolving CoachDecision versus final composer schema mismatch
---

# Prompt Contract Output Schema Split

## Goal

Split the PromptContract notion of output schema into two explicit concepts:

- `decision_output_schema`: what the current LLM call must return now;
- `output_schema`: the target user-facing/final layer for the route.

This removes the current ambiguity where read-only routes like `plan_lookup`
target a grounded final reply eventually, while the current conversation
`decide()` prompt still requires a `CoachDecision` JSON.

## Scope

In scope:

- add `decision_output_schema` to `PromptContract`;
- set read-only conversation decide routes to `CoachDecision` for now;
- keep terminal routes as `final_text`;
- keep `output_schema` as the future/final target;
- render `decision_output_schema` in the safe turn-scope renderer;
- keep `output_schema` out of that renderer until the prompt path is fully
  split.

Out of scope:

- changing runtime output behavior;
- injecting the contract renderer into conversation prompts;
- changing snapshots;
- changing final composer routing.

## TDD Steps

1. Add failing tests to `tests/test_prompt_contracts.py`:
   - `plan_lookup.decision_output_schema == "CoachDecision"`;
   - `plan_lookup.output_schema == "grounded_final_reply"`;
   - terminal routes use `final_text` for both current and final output.
2. Add a failing assertion to the turn-scope renderer test:
   - it includes `sortie decision: CoachDecision`;
   - it still does not include `grounded_final_reply`.
3. Implement the dataclass field and registry values.
4. Update the renderer.
5. Run focused tests and snapshots.
6. Run backend verification before commit.

## Acceptance

- PromptContract tests pass.
- Prompt module renderer tests pass.
- Prompt snapshots remain unchanged.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
