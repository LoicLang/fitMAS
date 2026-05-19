---
summary: Phase 9P plan for extended fallback census before reducing legacy decide provider
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9O
  - deciding whether conversation_decide_bridge or llm decision legacy can be reduced
  - adding extended smoke coverage for legacy provider reachability
---

# Decision Runtime Phase 9P Extended Census Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove where `legacy_decide` is still reachable outside core+daily before deleting or shrinking provider legacy.

**Architecture:** Phase 9P does not delete `legacy/conversation_decide_bridge.py` or `llm/decision_legacy.py`. It expands the real API census, classifies any remaining fallbacks by owner/source/reason, and adds gates so future deletions are driven by evidence instead of optimism.

**Tech Stack:** Python, `scripts/smoke_a_plus_api.py`, fallback census JSON, pytest via `./scripts/test-backend`.

---

## Why This Is The Right Next Move

9O removed dead modules because the import graph and core+daily census proved they had no runtime authority. `conversation_decide_bridge.py` and `llm/decision_legacy.py` are different: they are still wired as a broad fallback provider. Deleting them now would be fast, but unreliable; it could silently remove coverage for rare but important turns.

The scalable path is:

```text
measure wider -> classify every fallback -> migrate by owner -> then delete provider code
```

Trade-off:

- slower than immediate deletion;
- much safer for dogfood reliability;
- gives us a precise kill list instead of another refactor by guesswork.

## Scope

### In Scope

- Add an extended smoke battery beyond the current 42 core+daily scenarios.
- Run core + daily + extended with fallback census JSON.
- Make fallback summary fail by default if any fallback remains.
- Produce an owner table for anything still reaching `CoachDecision`.
- Add architecture/tests so the extended census exists and stays wired.
- Update docs with the new owner list and next deletion candidates.

### Out Of Scope

- Do not delete `legacy/conversation_decide_bridge.py`.
- Do not delete `llm/decision_legacy.py`.
- Do not fix reply polish in the same slice.
- Do not add prompt examples copied from smoke scenarios.
- Do not add deterministic parsing of free user text.

## Files

- Modify: `scripts/smoke_a_plus_api.py`
- Create: `scripts/smoke-decision-runtime-extended-census`
- Create: `tests/test_phase9p_extended_census_architecture.py`
- Modify: `tests/test_smoke_a_plus_api.py`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

## Extended Scenario Groups

Add `EXTENDED_SCENARIOS` to `scripts/smoke_a_plus_api.py`.

Coverage must include:

- pending variants:
  - reject pending;
  - confirm with modification;
  - short yes/no after non-pending context;
- execution variants:
  - activity done yesterday;
  - wrong sport correction;
  - longer-than-planned session;
- health/readiness variants:
  - pain + explicit request to adapt;
  - fatigue + no adaptation requested;
  - illness/rest request;
- availability variants:
  - one-day unavailable with affected session;
  - weekend unavailable;
  - new availability after prior constraint;
- read-only variants:
  - why this workout;
  - what changed recently;
  - what should I protect this week;
- clarification/elliptical variants:
  - "vendredi matin";
  - "plutot velo";
  - "non laisse tomber";
- command/memory variants:
  - preference update;
  - goal update;
  - equipment/location constraint.

Expected result is not necessarily zero fallback on first run. The output of 9P is the classified map.

## Tasks

### Task 1: Add a failing architecture test for the extended census surface

- [x] Create `tests/test_phase9p_extended_census_architecture.py`.
- [x] Assert `scripts/smoke_a_plus_api.py` defines `EXTENDED_SCENARIOS`.
- [x] Assert the CLI exposes `--extended`.
- [x] Assert `scripts/smoke-decision-runtime-extended-census` exists.
- [x] Assert extended scenarios do not duplicate core/daily names.

Run:

```bash
./scripts/test-backend tests/test_phase9p_extended_census_architecture.py -q
```

Expected before implementation: FAIL.

### Task 2: Add `EXTENDED_SCENARIOS`

- [x] Add the `EXTENDED_SCENARIOS` tuple.
- [x] Add `--extended` to select it.
- [x] Keep `--scenario` able to target names across core/daily/extended.
- [x] Do not change existing core/daily scenario expectations.

Important design rule:

```text
Extended scenarios are smoke probes, not prompt examples.
Do not copy them into prompts.
```

### Task 3: Add the wrapper

- [x] Create `scripts/smoke-decision-runtime-extended-census`.
- [ ] It must run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json /tmp/fitmas-9p-core-census.json --timeout 900
./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json /tmp/fitmas-9p-daily-census.json --timeout 1200
./scripts/smoke-a-plus-api --extended --skip-generated-week --fallback-census-json /tmp/fitmas-9p-extended-census.json --timeout 1600
./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-9p-core-census.json \
  /tmp/fitmas-9p-daily-census.json \
  /tmp/fitmas-9p-extended-census.json \
  --allow-fallbacks \
  --json-out /tmp/fitmas-9p-global-summary.json
```

Use `--allow-fallbacks` in 9P because this is discovery. The docs must record any fallbacks.

### Task 4: Add test coverage for CLI selection

- [x] Extend `tests/test_smoke_a_plus_api.py`.
- [x] Verify `--extended` selects only extended scenarios.
- [x] Verify `--scenario <extended_name>` works.
- [x] Verify duplicate scenario names fail the architecture test.

### Task 5: Run the extended census and classify output

- [x] Run targeted tests.
- [x] Run full backend.
- [x] Run `scripts/smoke-decision-runtime-extended-census`.
- [x] Inspect `/tmp/fitmas-9p-global-summary.json`.
- [x] Classify every fallback by:

```text
owner
source
reason
legacy_path
next_step
scenario
recommended slice
```

Potential classifications:

- canonical already handles it -> add hard gate, no migration needed;
- reply-only issue -> route to ReplyComposer/OutputVerifier;
- execution command gap -> route to CommandBus/execution bridge;
- memory command gap -> route to CommandBus/memory bridge;
- pending gap -> route to canonical pending bridge;
- true unsupported intent -> canonical no-write clarification/block;
- integration/provider issue -> keep legacy until isolated.

### Task 6: Update docs with deletion decision

- [x] Update `DECISION-RUNTIME-LEGACY-KILL-LIST.md`.
- [x] Update `DECISION-RUNTIME-REFACTOR.md`.
- [x] Update `BUILD-ORDER.md`.

Docs must answer:

```text
Can conversation_decide_bridge shrink now?
Can llm/decision_legacy shrink now?
Which owner must be migrated first?
Which reply-quality debts are separate from legacy deletion?
```

## Verification Commands

```bash
./scripts/test-backend tests/test_phase9p_extended_census_architecture.py tests/test_smoke_a_plus_api.py -q
./scripts/test-backend -q
./scripts/smoke-decision-runtime-extended-census
git diff --check
```

## Acceptance

- Extended smoke battery exists and is selectable.
- Core+daily remain zero fallback.
- Extended fallback map is written and documented.
- No legacy provider deletion happens without evidence.
- No prompt grows with smoke examples.
- Next slice is selected from measured owner counts.

## Result 2026-05-19

Fresh wrapper run after fixing `trivial_ack` terminal close:

```text
core+daily strict:
scenario_count=42
fallback_scenario_count=0
fallback_turn_count=0

core+daily+extended discovery:
scenario_count=62
fallback_scenario_count=1
fallback_turn_count=1
owner pending=1
source canonical_pending_provider=1
fallback scenario pending_reject_move turns=1
```

Classified remaining fallback:

```text
scenario=pending_reject_move
owner=pending
source=canonical_pending_provider
reason=fallback_legacy
legacy_path=CoachDecision
next_step=migrate pending rejection/cancel coverage to canonical pending outcomes
```

Decision:

- do not delete `conversation_decide_bridge.py` or `llm/decision_legacy.py` yet;
- next slice is pending rejection/cancel canonical handling;
- reply-quality debt is separate from legacy deletion.
