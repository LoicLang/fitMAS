---
summary: implementation plan for Decision Runtime Phase 8M decision_legacy internal split
read_when:
  - implementing Decision Runtime Phase 8M
  - refactoring fitmas.llm.decision_legacy
  - splitting legacy CoachDecision provider internals
---

# Decision Runtime Phase 8M Decision Legacy Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Split `backend/src/fitmas/llm/decision_legacy.py` into smaller legacy-internal modules without changing runtime behavior.

**Architecture:** 8M is not the canonical runtime cutover and does not delete `CoachDecision`. It turns `decision_legacy.py` into a thinner orchestrator around explicit legacy modules: models, prompt assembly, payload parsing/normalization, and action compilation/repair. Public imports through `fitmas.llm` stay compatible.

**Tech Stack:** Python, Pydantic, pytest, existing FitMAS LLM gateway, existing Decision Runtime Phase 8 architecture tests.

---

## Non-Negotiables

```text
1. No behavior change in conversation runtime.
2. No default-enable of canonical planning cutover.
3. No new parsing of free user text.
4. No new write path.
5. `fitmas.llm` public compatibility remains intact.
6. Existing tests that monkeypatch `fitmas.llm._request_*` keep working.
7. New modules must not import `conversation_pipeline.py`.
8. `decision_legacy.py` remains legacy orchestrator only.
```

## Target Files

Create:

- `backend/src/fitmas/llm/legacy_models.py`
- `backend/src/fitmas/llm/legacy_parser.py`
- `backend/src/fitmas/llm/legacy_prompt.py`
- `backend/src/fitmas/llm/legacy_action_compile.py`
- `tests/test_phase8m_decision_legacy_split_architecture.py`
- `tests/test_llm_legacy_parser.py`
- `tests/test_llm_legacy_action_compile.py`
- `scripts/smoke-decision-runtime-decision-legacy-split`

Modify:

- `backend/src/fitmas/llm/decision_legacy.py`
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/BUILD-ORDER.md`
- `docs/README.md`

## Task 1 - Architecture Gates

- [x] Add `tests/test_phase8m_decision_legacy_split_architecture.py`.
- [x] Assert the four target modules exist.
- [x] Assert `decision_legacy.py` imports those modules.
- [x] Assert `decision_legacy.py` no longer defines `CoachDecision`, `MutationDecision`, `parse_coach_decision_payload`, `_parse_llm_decision_payload`, `_maybe_compile_execution_actions_for_turn`, or `_maybe_compile_memory_actions_for_turn`.
- [x] Assert the new legacy modules do not import `fitmas.conversation_pipeline`.
- [x] Run the test red.

## Task 2 - Extract Legacy Models

- [x] Move Pydantic contracts and model constants into `legacy_models.py`.
- [x] Re-export the same names from `decision_legacy.py`.
- [x] Verify `from fitmas.llm import CoachDecision` and `from fitmas.llm.decision_legacy import CoachDecision` still return the same class object.

## Task 3 - Extract Legacy Parser

- [x] Move CoachDecision / MutationDecision parsing, action normalization, PlanPatch unwrap/normalization and message guards into `legacy_parser.py`.
- [x] Keep parser state internal to `legacy_parser.py`.
- [x] Expose `get_last_invalid_decision_payload()` for `decide()` repair flow.
- [x] Re-export legacy private compatibility names from `decision_legacy.py`.
- [x] Add direct parser tests in `tests/test_llm_legacy_parser.py`.
- [x] Run parser tests green.

## Task 4 - Extract Prompt Assembly

- [x] Add `legacy_prompt.py` with `LegacyDecisionPromptBundle`.
- [x] Move prompt policy, selected facts, time context, layered prompt assembly and tool-budget selection into that module.
- [x] Keep `decision_legacy.decide()` responsible for orchestration only.
- [x] Preserve existing prompt trace logging.

## Task 5 - Extract Action Compilation

- [x] Move memory/execution action compiler and repair helpers into `legacy_action_compile.py`.
- [x] Inject `request_structured_json_fn` from `decision_legacy.py` so monkeypatches of `fitmas.llm._request_structured_json` still work.
- [x] Re-export wrapper private names from `decision_legacy.py`.
- [x] Add direct compiler tests in `tests/test_llm_legacy_action_compile.py`.
- [x] Run compiler tests green.

## Task 6 - Smoke Wrapper

- [x] Create `scripts/smoke-decision-runtime-decision-legacy-split`.
- [x] Wrapper runs 8M tests, 8L tests, and `scripts/smoke-decision-runtime-decide-shrink`.
- [x] Make wrapper executable.

## Task 7 - Docs

- [x] Mark Phase 8M delivered in `DECISION-RUNTIME-REFACTOR.md`.
- [x] Update `DECISION-RUNTIME-LEGACY-KILL-LIST.md`.
- [x] Update `BUILD-ORDER.md`.
- [x] Add the plan to `docs/README.md`.
- [x] Add verification evidence to this plan.

## Verification Gate

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_llm_legacy_parser.py \
  tests/test_llm_legacy_action_compile.py \
  tests/test_llm_package_compat.py \
  tests/test_coach_decision_actions.py \
  tests/test_llm_tools.py \
  tests/test_decide_error_typing.py
```

Run:

```bash
./scripts/smoke-decision-runtime-decision-legacy-split
```

Run:

```bash
./scripts/test-backend -q
```

## Acceptance Criteria

```text
1. decision_legacy.py is smaller and no longer owns models/parser/compiler logic.
2. Public `fitmas.llm` imports remain compatible.
3. Existing monkeypatch tests on `fitmas.llm._request_*` still pass.
4. 8L decide authority boundaries remain green.
5. Planning cutover remains opt-in.
6. Full backend suite passes.
```

## Implementation Result

Delivered locally on 2026-05-16.

Key results:

- `decision_legacy.py` went from 2873 lines to 1467 lines.
- `legacy_models.py` owns legacy Pydantic contracts.
- `legacy_parser.py` owns CoachDecision/MutationDecision parsing,
  normalization and payload guards.
- `legacy_prompt.py` owns legacy conversation prompt assembly and tool budget
  selection.
- `legacy_action_compile.py` owns memory/execution action compilers and repair
  helpers.
- Public `fitmas.llm` compatibility remains intact, including typed pending
  resolution classes.
- `fitmas.llm._request_*` monkeypatch compatibility remains intact through
  request function injection.
- Commands/pending canonical lanes remain default-on.
- Planning cutover remains opt-in.

Verification evidence:

```bash
./scripts/test-backend -q \
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_llm_legacy_parser.py \
  tests/test_llm_legacy_action_compile.py \
  tests/test_llm_package_compat.py \
  tests/test_coach_decision_actions.py \
  tests/test_llm_json.py
```

Result:

```text
31 passed
```

```bash
./scripts/test-backend -q tests/test_llm_tools.py tests/test_decide_error_typing.py tests/test_core_flows.py -k "tool or decide_accepts_coach_decision_plan_patch_payload or decision_legacy or activity_highlights"
```

Result:

```text
67 passed, 126 deselected
```

```bash
./scripts/test-backend -q tests/test_conversation_pending_bridge.py tests/test_llm_package_compat.py tests/test_phase8m_decision_legacy_split_architecture.py
```

Result:

```text
18 passed
```

```bash
./scripts/smoke-decision-runtime-decision-legacy-split
```

Result:

```text
RESULT: OK
```

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py \
  tests/test_phase8d_bridge_shrink_architecture.py \
  tests/test_phase8e_understanding_cutover_architecture.py \
  tests/test_phase8f_command_extraction_architecture.py \
  tests/test_phase8g_pending_resolution_architecture.py \
  tests/test_phase8h_pending_reply_architecture.py \
  tests/test_phase8i_canonical_flag_dogfood_architecture.py \
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_phase8m_decision_legacy_split_architecture.py
```

Result:

```text
76 passed
```

```bash
./scripts/test-backend -q
```

Result:

```text
1245 passed, 11 skipped, 11 subtests passed
```
