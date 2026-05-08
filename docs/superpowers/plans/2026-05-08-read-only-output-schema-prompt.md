---
summary: implementation plan for a minimal read-only conversation output schema prompt
read_when:
  - reducing read_only conversation prompts
  - modifying CoachDecision output schema prompt modules
  - changing plan_lookup or fact_recall prompt composition
---

# Read-Only Output Schema Prompt

## Goal

Give read-only routes a smaller `CoachDecision` output schema.

After filtering mutation modules, read-only routes still receive the full output
schema with `plan_patch`, memory actions, execution actions and mutation
examples. That keeps unnecessary action affordances in the model's context.

This slice keeps the current runtime contract (`CoachDecision`) but narrows the
prompted shape:

- `response_type`: `reply | no_change`;
- no mutation decision;
- no `plan_patch`;
- no memory writes;
- no execution writes;
- no pending mutation resolution;
- user-facing `fitmas_message` grounded in the supplied truth blocks.

## Scope

In scope:

- add a minimal read-only output schema builder;
- use it for `read_only` and `terminal_text` contract compositions that still
  pass through the conversation system prompt;
- keep the full output schema for draft/write/legacy routes;
- update the plan lookup snapshot.

Out of scope:

- changing runtime parsing of `CoachDecision`;
- changing final composer routing;
- removing `CoachDecision` entirely from read-only routes;
- changing terminal close lane behavior.

## TDD Steps

1. Add failing tests:
   - read-only system prompt includes the minimal schema;
   - read-only system prompt excludes full action schema details;
   - draft-action prompt still includes the full schema.
2. Implement `build_read_only_output_schema_system_text()`.
3. Select output schema builder by contract capability.
4. Update prompt snapshot.
5. Run focused tests and backend verification.

## Acceptance

- Read-only prompt snapshot shrinks again.
- Draft/action prompts still include full mutation/action schema.
- Backend suite remains green.
- One atomic implementation commit follows the plan commit.
