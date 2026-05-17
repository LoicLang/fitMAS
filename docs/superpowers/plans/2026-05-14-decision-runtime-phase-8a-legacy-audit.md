---
summary: implementation plan for Decision Runtime Phase 8A legacy audit and kill list
read_when:
  - implementing Decision Runtime Phase 8A
  - auditing legacy CoachDecision, MutationDecision, final_reply or heartbeat paths
  - preparing Phase 8B cutover
  - adding architecture tests around legacy boundaries
---

# Decision Runtime Phase 8A Legacy Audit Plan

> **For agentic workers:** Phase 8A is an audit slice. Do not delete runtime code in this slice.

**Goal:** Make the remaining legacy authority explicit before any destructive
cleanup. The output is a kill list, tests that keep it current, and docs that
tell the next agent where to cut.

**Status 2026-05-14:** implemented locally.

## Scope

Allowed:

- add `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`;
- add static audit tests;
- update `DECISION-RUNTIME-REFACTOR.md`, `BUILD-ORDER.md` and `docs/README.md`;
- inspect current legacy importers and tool surfaces.

Forbidden:

- no deletion of runtime code;
- no cutover default change;
- no new fallback branch;
- no new prompt rule;
- no new parser over free user text;
- no widening of `conversation_pipeline.py`.

## Checklist

- [x] Run `./scripts/docs:list`.
- [x] Read the current Decision Runtime canon and Build Order.
- [x] Inspect importers of `CoachDecision` and `MutationDecision`.
- [x] Inspect direct callers of `fitmas.final_reply`.
- [x] Inspect planning/heartbeat cutover flags.
- [x] Inspect `WeeklyPlan` / `DayPlan` runtime surfaces.
- [x] Create the legacy kill list doc.
- [x] Add static tests that force the kill list to stay synchronized.
- [x] Update docs index and phase status.
- [x] Run targeted verification.

## Audit Findings

The remaining blockers are:

- `conversation_pipeline.py` still acts as mega-orchestrator;
- `llm/decision_legacy.py`, `conversation_prompt_modules.py` and
  `prompt_contracts.py` still carry `CoachDecision`;
- `MutationDecision` importers still exist in runtime-support files;
- `final_reply.py` still has direct callers outside the Phase 5 backend bridge;
- heartbeat internals still have their own prompt/tool-loop/guard stack;
- planning tools still expose candidate/draft legacy helpers;
- `WeeklyPlan` / `DayPlan` still appear in read/compat paths.

## Acceptance

```text
./scripts/test-backend -q tests/test_phase8a_legacy_audit.py
```

must pass.

Recommended broader verification:

```text
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase7_heartbeat_architecture.py \
  tests/test_phase8a_legacy_audit.py
```

## Next Slice

Phase 8B should not start by deleting files. It should first run the planning
and heartbeat cutovers flag-on in local/staging, then remove one active legacy
decision route at a time.
