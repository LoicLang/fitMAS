---
summary: implementation plan for Decision Runtime Phase 8O CoachDecision artifact boundary
read_when:
  - implementing Decision Runtime Phase 8O
  - reducing CoachDecision runtime authority
  - migrating conversation bridges away from raw legacy LLM models
---

# Decision Runtime Phase 8O CoachDecision Artifact Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Stop the conversation runtime and legacy conversation bridges from consuming raw `CoachDecision` / `MutationDecision` objects directly.

**Architecture:** 8O does not delete `CoachDecision` and does not rewrite `decide()` yet. It creates a stable boundary artifact immediately after the legacy provider returns. Raw LLM models remain inside the LLM/provider/parser compatibility zone; the runtime receives a neutral, typed artifact with the few fields still needed while canonical `CoachUnderstanding`, `DecisionOutcome`, command services and reply composition continue to take over.

**Tech Stack:** Python, pytest, existing legacy conversation bridges, existing Decision Runtime Phase 8 architecture tests.

---

## Non-Negotiables

```text
1. No visible coach behavior change.
2. No default-enable of canonical planning cutover.
3. No new deterministic parsing of free user text.
4. No new write path.
5. No new prompt contract.
6. No new local fallback in conversation_pipeline.py.
7. Raw CoachDecision / MutationDecision may exist only in the LLM/provider/parser
   compatibility zone and the new artifact adapter.
8. Conversation bridges consume LegacyCoachDecisionArtifact, not raw model fields.
9. ReplyComposer remains the only canonical final reply target.
10. Existing provider monkeypatch compatibility from 8N remains intact.
```

## Why This Slice Exists

After 8N, `backend/src/fitmas/llm/decision_legacy.py` is smaller and provider/tool-loop/schema-repair mechanics are extracted. But `CoachDecision` is still the live contract crossing into the conversation runtime:

```text
conversation_pipeline.py
  -> run_legacy_coach_decision(...)
  -> raw CoachDecision
  -> command bridge reads memory_actions / execution_actions / plan_patch
  -> pending bridge reads pending_resolution / response_type / plan_patch
  -> planning bridge reads plan_patch / fitmas_message
  -> reply bridge reads confirmation_reason / fitmas_message / response_type
  -> understanding shadow converts raw CoachDecision back into CoachUnderstanding
```

That is too much authority for a legacy LLM model. 8O inserts one boundary:

```text
LLM legacy provider/parser
  -> raw CoachDecision | MutationDecision | None
  -> LegacyCoachDecisionArtifact
  -> conversation runtime bridges
```

The artifact is not the final architecture. It is a migration joint. It lets 8P+ shrink `decide()` and eventually replace the legacy contract without touching every bridge again.

## Target Shape

Create:

- `backend/src/fitmas/legacy/coach_decision_artifact.py`
  Neutral dataclasses and helpers for the legacy decision boundary.
- `tests/test_phase8o_coachdecision_artifact_architecture.py`
  Static gates proving raw `CoachDecision` no longer leaks into conversation bridges.
- `tests/test_coach_decision_artifact.py`
  Unit tests for artifact conversion and payload serialization.
- `scripts/smoke-decision-runtime-coachdecision-artifact`
  Local deterministic wrapper for 8O gates plus the 8N provider/tool-loop
  regression pack. Live API/LLM dogfood remains separate.

Modify:

- `backend/src/fitmas/legacy/coach_decision_provider.py`
- `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/legacy/conversation_decision_bridge.py`
- `backend/src/fitmas/legacy/conversation_command_bridge.py`
- `backend/src/fitmas/legacy/coach_command_adapter.py`
- `backend/src/fitmas/legacy/conversation_pending_bridge.py`
- `backend/src/fitmas/legacy/conversation_planning_bridge.py`
- `backend/src/fitmas/legacy/conversation_coach_decision_reply_bridge.py`
- `backend/src/fitmas/legacy/coach_understanding_adapter.py`
- `backend/src/fitmas/legacy/understanding_shadow.py`
- `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Existing focused tests for the modified bridges.
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/BUILD-ORDER.md`
- `docs/README.md`
- This plan file after implementation with evidence.

## Boundary Model

Add a neutral artifact that does not import `fitmas.llm` models.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

LegacyDecisionArtifactKind = Literal[
    "coach_decision",
    "legacy_readonly",
    "none",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class LegacyCoachDecisionArtifact:
    kind: LegacyDecisionArtifactKind
    response_type: str = "reply"
    rationale: str = ""
    reply_hint: str = ""
    confirmation_reason: str | None = None
    mutation_decision: Any | None = None
    plan_patch: Any | None = None
    memory_actions: tuple[Any, ...] = ()
    execution_actions: tuple[Any, ...] = ()
    pending_resolution: Any | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str = "coach_decision"

    @property
    def is_coach_decision(self) -> bool:
        return self.kind == "coach_decision"

    @property
    def is_legacy_readonly(self) -> bool:
        return self.kind == "legacy_readonly"

    @property
    def has_value(self) -> bool:
        return self.kind not in {"none", "unsupported"}
```

Conversion rule:

```text
raw CoachDecision        -> kind="coach_decision"
raw MutationDecision no_change with fitmas_message
                         -> kind="legacy_readonly"
None                     -> kind="none"
anything else            -> kind="unsupported"
```

Naming rule:

```text
fitmas_message becomes reply_hint at the runtime boundary.
reply_hint is input context for composers only; it is not a committed action claim.
```

## Task 1 - Architecture Gates Red

**Files:**

- Create: `tests/test_phase8o_coachdecision_artifact_architecture.py`

- [x] Add AST helpers matching previous Phase 8 architecture tests.
- [x] Assert `legacy/coach_decision_artifact.py` exists.
- [x] Assert `legacy/coach_decision_provider.py` imports `LegacyCoachDecisionArtifact`.
- [x] Assert `legacy/conversation_decide_bridge.py` returns the provider artifact, not `result.decision`.
- [x] Assert these conversation-facing modules do not contain direct `.fitmas_message` access:

```text
conversation_pipeline.py
legacy/conversation_command_bridge.py
legacy/coach_command_adapter.py
legacy/conversation_pending_bridge.py
legacy/conversation_planning_bridge.py
legacy/conversation_coach_decision_reply_bridge.py
legacy/planning_runtime_adapter.py
legacy/understanding_shadow.py
```

- [x] Assert these conversation-facing modules do not import `CoachDecision` or `MutationDecision` from `fitmas.llm`:

```text
conversation_pipeline.py
legacy/conversation_decide_bridge.py
legacy/conversation_command_bridge.py
legacy/conversation_pending_bridge.py
legacy/conversation_planning_bridge.py
legacy/conversation_coach_decision_reply_bridge.py
legacy/planning_runtime_adapter.py
legacy/understanding_shadow.py
```

- [x] Allow raw model imports only in:

```text
llm/legacy_models.py
llm/legacy_parser.py
llm/legacy_action_compile.py
llm/decision_legacy.py
legacy/coach_understanding_adapter.py   # temporary, until artifact conversion owns all paths
tests/
```

- [x] Assert `conversation_pipeline.py` uses an artifact name such as `decision_artifact` or `legacy_decision_artifact`, not a raw `decision` variable for the legacy provider result.
- [x] Assert planning cutover remains default-off:

```text
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER default=False
```

- [x] Run the new architecture test and verify it fails before implementation:

```bash
./scripts/test-backend -q tests/test_phase8o_coachdecision_artifact_architecture.py
```

Expected first failure: missing `legacy/coach_decision_artifact.py`.

## Task 2 - Add LegacyCoachDecisionArtifact

**Files:**

- Create: `backend/src/fitmas/legacy/coach_decision_artifact.py`
- Create: `tests/test_coach_decision_artifact.py`

- [x] Define `LegacyCoachDecisionArtifact`.
- [x] Define `legacy_decision_artifact_from_raw(value: Any) -> LegacyCoachDecisionArtifact`.
- [x] Define `legacy_decision_artifact_payload(artifact) -> dict[str, Any]`.
- [x] Define `legacy_decision_artifact_json(artifact) -> str`.
- [x] Use structural checks with `getattr` / `hasattr`; do not import `fitmas.llm.CoachDecision`.
- [x] Normalize tuple fields:

```text
memory_actions
execution_actions
```

- [x] Preserve the legacy response surface as data:

```text
response_type
rationale
reply_hint
confirmation_reason
mutation_decision
plan_patch
pending_resolution
```

- [x] Add tests:

```text
coach_decision raw object -> coach_decision artifact
legacy readonly raw object -> legacy_readonly artifact
None -> none artifact
unknown object -> unsupported artifact
payload serialization includes reply_hint, not fitmas_message
tuple normalization for actions is stable
```

## Task 3 - Move Provider Result To Artifact

**Files:**

- Modify: `backend/src/fitmas/legacy/coach_decision_provider.py`
- Modify: `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- Modify: `tests/test_coach_decision_provider.py`
- Modify: `tests/test_conversation_decide_bridge.py`

- [x] Change `CoachDecisionResult` to carry:

```python
artifact: LegacyCoachDecisionArtifact
raw_decision: Any | None = None
```

- [x] Keep a temporary `decision` property only if required for old tests or non-runtime compatibility:

```python
@property
def decision(self) -> Any | None:
    return self.raw_decision
```

Runtime code must not consume that property.

- [x] Provider flow:

```text
raw = decide_fn(...)
artifact = legacy_decision_artifact_from_raw(raw)
return CoachDecisionResult(artifact=artifact, raw_decision=raw, ...)
```

- [x] Exception flow:

```text
return CoachDecisionResult(
    artifact=LegacyCoachDecisionArtifact(kind="none", source="coach_decision"),
    raw_decision=None,
    error_type=...,
)
```

- [x] Update `run_legacy_coach_decision(...)` to return `result.artifact`.
- [x] Update turn trace to record artifact metadata, not raw model metadata:

```text
legacy_decide.ok
legacy_decide.source
legacy_decide.artifact_kind
legacy_decide.response_type
legacy_decide.has_plan_patch
legacy_decide.has_pending_resolution
legacy_decide.memory_action_count
legacy_decide.execution_action_count
```

- [x] Tests verify:

```text
provider still forwards all request kwargs
provider returns artifact.kind="coach_decision"
provider preserves raw_decision for temporary compatibility
decide bridge returns artifact
decide bridge trace does not serialize raw CoachDecision
provider exception returns artifact.kind="none"
```

## Task 4 - Migrate Conversation Runtime And Bridges

**Files:**

- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/legacy/conversation_decision_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_command_bridge.py`
- Modify: `backend/src/fitmas/legacy/coach_command_adapter.py`
- Modify: `backend/src/fitmas/legacy/conversation_pending_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_planning_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_coach_decision_reply_bridge.py`
- Update corresponding focused tests.

- [x] Rename the pipeline variable:

```text
decision -> legacy_decision_artifact
```

from the provider bridge onward.

- [x] Replace `is_coach_decision(decision)` with artifact checks:

```python
artifact.is_coach_decision
artifact.is_legacy_readonly
artifact.has_value
```

- [x] Replace `turn_context["coach_decision"] = coach_decision_payload(...)` with artifact payload.
- [x] Update command bridge parameter names:

```text
decision -> decision_artifact
```

- [x] Update command extraction to read:

```text
artifact.memory_actions
artifact.execution_actions
artifact.response_type
artifact.plan_patch
```

- [x] Keep command source stable as `"coach_decision"` unless tests show metric consumers require a new source name.
- [x] Update pending bridge to read:

```text
artifact.pending_resolution
artifact.response_type
artifact.plan_patch
```

- [x] Update planning bridge to pass:

```text
artifact.reply_hint
```

as `original_reply`.

- [x] Update reply bridge to compose from:

```text
artifact.confirmation_reason or artifact.reply_hint
artifact.response_type
```

- [x] Update readonly legacy branch to use `artifact.is_legacy_readonly` and `artifact.reply_hint`.
- [x] Preserve all existing `ConversationTurnOutcome` modes.
- [x] Tests verify the same output/modes for:

```text
coach reply
no_change + execution report
pending accept/reject/modify/ignore
planning runtime cutover attempt
legacy readonly no_change
unsupported artifact blocked by legacy_decision_contract_disabled_outcome
```

## Task 5 - Migrate Understanding Shadow And Planning Adapter

**Files:**

- Modify: `backend/src/fitmas/legacy/coach_understanding_adapter.py`
- Modify: `backend/src/fitmas/legacy/understanding_shadow.py`
- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `tests/test_coach_understanding_adapter.py`
- Modify: `tests/test_conversation_understanding_shadow.py`
- Modify: `tests/test_conversation_planning_runtime_adapter.py`

- [x] Add:

```python
def coach_decision_artifact_to_understanding(
    artifact: LegacyCoachDecisionArtifact,
) -> CoachUnderstanding:
    ...
```

- [x] Keep `coach_decision_to_understanding(raw)` only as a compatibility wrapper:

```text
raw -> artifact -> CoachUnderstanding
```

- [x] Update `understanding_shadow` to accept artifact and call artifact conversion.
- [x] Update `planning_runtime_adapter` to accept artifact and call artifact conversion when canonical understanding is absent.
- [x] Preserve the requested-change mapping:

```text
mutation_decision -> RequestedPlanChange
plan_patch -> RequestedPlanChange
pending_resolution -> PendingResolution
memory/execution actions -> UserSignal
```

- [x] Tests verify artifact conversion produces the same `CoachUnderstanding` previously produced from raw `CoachDecision`.

## Task 6 - Strengthen CoachDecision Contract Gates

**Files:**

- Modify: `tests/test_phase8o_coachdecision_artifact_architecture.py`
- Optionally modify older Phase 8 architecture tests if their wording is stale.

- [x] Add a source scan proving only the artifact module may expose `fitmas_message` as a boundary concern.
- [x] Add a source scan proving `conversation_pipeline.py` does not pass raw `CoachDecision` into:

```text
apply_coach_decision_commands
apply_pending_resolution
maybe_handle_planning_runtime_cutover
compose_coach_decision_reply
shadow_understanding_from_legacy_decision
```

- [x] Add a source scan proving direct `CoachDecisionResult.decision` consumption is limited to tests or compatibility properties.
- [x] Add a source scan proving `CoachDecision` remains provider/parser compatibility, not runtime authority.

## Task 7 - Smoke Wrapper And Regression Pack

**Files:**

- Create: `scripts/smoke-decision-runtime-coachdecision-artifact`

- [x] Add executable wrapper:

```bash
#!/usr/bin/env bash
set -euo pipefail

./scripts/test-backend -q \
  tests/test_phase8o_coachdecision_artifact_architecture.py \
  tests/test_coach_decision_artifact.py \
  tests/test_coach_decision_provider.py \
  tests/test_conversation_decide_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_coach_understanding_adapter.py \
  tests/test_conversation_understanding_shadow.py

./scripts/test-backend -q \
  tests/test_phase8n_provider_tool_loop_architecture.py \
  tests/test_llm_legacy_provider.py \
  tests/test_llm_legacy_schema_repair.py \
  tests/test_llm_legacy_tool_loop.py \
  tests/test_llm_package_compat.py \
  tests/test_prompt_observability.py \
  tests/test_llm_tools.py \
  tests/test_decide_error_typing.py \
  tests/test_coach_decision_actions.py

echo "RESULT: OK"
```

- [x] Run:

```bash
chmod +x scripts/smoke-decision-runtime-coachdecision-artifact
./scripts/smoke-decision-runtime-coachdecision-artifact
```

## Task 8 - Documentation

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`
- Modify: this plan file.

- [x] Document Phase 8O status and evidence.
- [x] Update remaining debt:

```text
CoachDecision still exists in the LLM/parser/provider zone.
decision_legacy.py still orchestrates legacy decide().
canonical planning cutover remains opt-in.
Next slice can shrink decide() internals or replace provider output with canonical CoachUnderstanding first.
```

- [x] Update docs list/index if the repo pattern requires it.

## Required Verification

Run targeted gates first:

```bash
./scripts/test-backend -q tests/test_phase8o_coachdecision_artifact_architecture.py
./scripts/test-backend -q tests/test_coach_decision_artifact.py tests/test_coach_decision_provider.py tests/test_conversation_decide_bridge.py
./scripts/smoke-decision-runtime-coachdecision-artifact
```

Then run Phase 8 regression pack:

```bash
./scripts/test-backend -q \
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
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_phase8n_provider_tool_loop_architecture.py \
  tests/test_phase8o_coachdecision_artifact_architecture.py
```

Finally run full backend if targeted gates pass:

```bash
./scripts/test-backend
```

## Acceptance Criteria

```text
1. Conversation runtime receives LegacyCoachDecisionArtifact, not raw CoachDecision.
2. Conversation-facing bridges no longer read .fitmas_message directly.
3. Provider/parser/LLM compatibility remains intact.
4. Canonical planning cutover remains default-off.
5. No new deterministic free-text parsing.
6. No new write path.
7. Existing behavior and response modes remain stable.
8. New architecture tests prevent raw CoachDecision from leaking back into runtime bridges.
```

## What 8O Enables Next

8O makes the next slice cleaner. After this boundary, possible 8P options are:

```text
Option A - Shrink decide() further:
  extract onboarding/week-plan/fact helper orchestration out of decision_legacy.py.

Option B - Canonical provider pivot:
  make provider output CoachUnderstanding for non-planning lanes by default and keep
  LegacyCoachDecisionArtifact only as fallback.

Option C - Planning contract reduction:
  remove direct plan_patch/requires_confirmation from the runtime-visible artifact
  when canonical planning cutover is ready.
```

Recommended next step after 8O: choose between A and B based on dogfood stability. If behavior is stable, B accelerates the real architecture. If friction remains in legacy decide internals, A reduces risk first.

## Implementation Evidence - 2026-05-17

Delivered:

```text
LegacyCoachDecisionArtifact boundary added.
Provider result now returns artifact + raw_decision compatibility.
Conversation pipeline consumes legacy_decision_artifact.
Conversation-facing bridges no longer read raw fitmas_message.
Unsupported mutating MutationDecision remains traceable and blocked.
Artifact -> CoachUnderstanding conversion supports shadow/planning adapters.
8O smoke wrapper is deterministic-only; live API/LLM dogfood is not inherited.
```

Verification:

```bash
./scripts/test-backend -q tests/test_phase8o_coachdecision_artifact_architecture.py tests/test_coach_decision_artifact.py tests/test_coach_decision_provider.py tests/test_conversation_decide_bridge.py tests/test_conversation_command_bridge.py tests/test_conversation_pending_bridge.py tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_coach_decision_reply_bridge.py tests/test_coach_understanding_adapter.py tests/test_conversation_understanding_shadow.py tests/test_phase8b_planning_cutover.py
# 57 passed

./scripts/test-backend -q tests/test_core_flows.py
# 122 passed

./scripts/test-backend -q tests/test_phase8n_provider_tool_loop_architecture.py tests/test_llm_legacy_provider.py tests/test_llm_legacy_schema_repair.py tests/test_llm_legacy_tool_loop.py tests/test_llm_package_compat.py tests/test_prompt_observability.py tests/test_llm_tools.py tests/test_decide_error_typing.py tests/test_coach_decision_actions.py
# 118 passed

./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8j_canonical_planning_cutover_architecture.py tests/test_phase8k_canonical_default_lanes_architecture.py tests/test_phase8l_decide_authority_architecture.py tests/test_phase8m_decision_legacy_split_architecture.py tests/test_phase8n_provider_tool_loop_architecture.py tests/test_phase8o_coachdecision_artifact_architecture.py
# 93 passed

./scripts/test-backend
# 1281 passed, 11 skipped
```

Wrapper note:

```text
./scripts/smoke-decision-runtime-coachdecision-artifact
  - 52 8O deterministic tests passed.
  - 118 8N deterministic tests passed.
  - RESULT: OK.
  - no live API/LLM smoke is launched by this wrapper.
```
