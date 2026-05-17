---
summary: implementation plan for Decision Runtime Phase 8B cutover parity gates
read_when:
  - implementing Decision Runtime Phase 8B
  - enabling planning or heartbeat runtime cutovers
  - proving parity before deleting legacy routes
  - adding smoke gates for Decision Runtime activation
---

# Decision Runtime Phase 8B Cutover Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that planning conversation turns and heartbeat triggers can run through the Decision Runtime cutover paths under flags, without silently falling back to competing legacy decision routes.

**Architecture:** Phase 8B is a parity gate, not a deletion phase. Existing adapters in `fitmas.legacy` remain as bridges, but flag-on behavior becomes stricter and observable: if a typed planning change is applicable to the runtime, it must produce a runtime outcome or a safe runtime block, not slide back into `MutationDecision` / mixed candidate / direct `final_reply` branches. Heartbeat stays adapter-based, but enforcement and smoke gates prove all proactive entrypoints can run through `InputEvent -> DecisionOutcome`.

**Tech Stack:** Python 3.13, pytest, existing zsh smoke wrappers, `DecisionOutcome`, `PlanningDecisionResult`, `HeartbeatRuntimeResult`, environment flags.

---

**Status 2026-05-14:** implemented locally. Targeted tests, flag-on unit gate
and `./scripts/smoke-decision-runtime-cutover` passed. Legacy remains present
physically for Phase 8C.

## Non-Negotiables

```text
1. Do not enable cutover flags by default in application code.
2. Do not delete legacy files in Phase 8B.
3. Do not add deterministic parsing of free user text.
4. Do not add a new reply composer or local canned reply path.
5. Do not add DB writes outside CommandService / existing legacy writer bridges.
6. Flag-off behavior must remain unchanged.
7. Flag-on planning behavior must not silently fall through to legacy planning branches when a typed requested change exists.
8. Flag-on heartbeat behavior must pass through the Phase 7 runtime adapter for scheduler/manual/debug/ops paths.
```

## Current Inputs

Phase 8A created the kill list:

```text
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
```

Existing cutover flags:

```text
FITMAS_PLANNING_RUNTIME_CUTOVER=1
FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1
```

Existing bridge files:

```text
backend/src/fitmas/legacy/planning_runtime_adapter.py
backend/src/fitmas/legacy/heartbeat_runtime_adapter.py
backend/src/fitmas/app/telegram/scheduler.py
```

## File Map

Create:

```text
scripts/smoke-decision-runtime-cutover
tests/test_phase8b_cutover_harness.py
tests/test_phase8b_planning_cutover.py
tests/test_phase8b_heartbeat_cutover.py
```

Modify:

```text
backend/src/fitmas/legacy/planning_runtime_adapter.py
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/app/telegram/scheduler.py          only if tests expose a missing metadata/enforcement path
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/DECISION-RUNTIME-REFACTOR.md
docs/BUILD-ORDER.md
```

Forbidden unless a test proves it is unavoidable:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/prompt_contracts.py
backend/src/fitmas/tools/registry.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/skills/heartbeat/heartbeat.py
```

## Target Behavior

Flag-off:

```text
conversation_pipeline.py behaves exactly as before.
heartbeat scheduler/manual/debug/ops behave exactly as before.
```

Flag-on planning:

```text
CoachDecision/MutationDecision legacy artifact
-> CoachUnderstanding adapter
-> RequestedPlanChange if applicable
-> Planning Runtime
-> PlanningCommandService
-> DecisionOutcome
-> DecisionReplyComposer
-> ConversationTurnOutcome
```

If the artifact contains an applicable typed requested planning change but the
runtime cannot handle it, return a safe runtime block:

```text
response_mode="planning_runtime_unhandled"
mutation_applied=False
pending_confirmation=False
reply from DecisionOutcome / composer fallback
```

It must not continue to:

```text
_maybe_handle_plan_adaptation_candidates
MutationDecision direct apply
requires_confirmation direct PlanPatch branch
legacy pending acceptance branch
```

Flag-on heartbeat:

```text
scheduler/manual/debug/ops
-> build InputEvent
-> HeartbeatRuntimeResult
-> DecisionOutcome(answer | plan_pending | no_send)
-> verifier shadow/enforced
-> delivery persists only after successful send
```

## Task 1 — Add Cutover Harness Script

**Files:**

- Create: `scripts/smoke-decision-runtime-cutover`
- Create: `tests/test_phase8b_cutover_harness.py`

- [ ] **Step 1: Write failing tests for the harness**

Create `tests/test_phase8b_cutover_harness.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke-decision-runtime-cutover"


def test_cutover_harness_exists_and_sets_runtime_flags() -> None:
    assert SCRIPT.exists()
    source = SCRIPT.read_text(encoding="utf-8")

    assert "FITMAS_PLANNING_RUNTIME_CUTOVER=1" in source
    assert "FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1" in source
    assert "FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1" in source


def test_cutover_harness_runs_targeted_tests_before_real_smokes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    test_index = source.index("tests/test_phase8b_planning_cutover.py")
    smoke_index = source.index("smoke-real-conversations")
    assert test_index < smoke_index


def test_cutover_harness_covers_critical_smoke_scenarios() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    required = {
        "heartbeat_non_completion",
        "compound_non_completion_swap",
        "golden_case_autonomy",
        "today_unavailability",
        "move_easy_then_confirm",
    }

    assert sorted(token for token in required if token not in source) == []
```

- [ ] **Step 2: Run the test and verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8b_cutover_harness.py
```

Expected:

```text
FAIL because scripts/smoke-decision-runtime-cutover does not exist
```

- [ ] **Step 3: Add the harness script**

Create `scripts/smoke-decision-runtime-cutover`:

```zsh
#!/usr/bin/env zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

export FITMAS_PLANNING_RUNTIME_CUTOVER=1
export FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1
export FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1

echo "== Decision Runtime cutover unit gates =="
"$repo_root/scripts/test-backend" -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase7_heartbeat_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_planning_cutover.py \
  tests/test_phase8b_heartbeat_cutover.py

echo "== Decision Runtime conversation smokes =="
"$repo_root/scripts/smoke-real-conversations" \
  --scenario heartbeat_non_completion \
  --scenario compound_non_completion_swap \
  --scenario golden_case_autonomy \
  --scenario today_unavailability

echo "== Decision Runtime A+ API smoke =="
"$repo_root/scripts/smoke-a-plus-api" \
  --scenario move_easy_then_confirm \
  --timeout 240 \
  --startup-timeout 45
```

Run:

```bash
chmod +x scripts/smoke-decision-runtime-cutover
```

- [ ] **Step 4: Run the harness tests**

Run:

```bash
./scripts/test-backend -q tests/test_phase8b_cutover_harness.py
```

Expected:

```text
3 passed
```

## Task 2 — Add Planning Runtime Adapter Attempt Object

**Files:**

- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `tests/test_conversation_planning_runtime_adapter.py`
- Create: `tests/test_phase8b_planning_cutover.py`

- [ ] **Step 1: Write failing tests for adapter applicability**

Add to `tests/test_phase8b_planning_cutover.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision
from fitmas.llm import CoachDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def _plan_patch_decision() -> CoachDecision:
    return CoachDecision(
        response_type="plan_patch",
        rationale="move",
        fitmas_message="Je propose de bouger la seance.",
        plan_patch=PlanPatch(
            coach_message="patch",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=42,
                    target_date="2026-05-15",
                    rationale="move",
                )
            ],
        ),
    )


def test_planning_runtime_attempt_marks_non_planning_as_not_applicable() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture",
        fitmas_message="Rien a changer.",
    )

    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision=decision,
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="ok",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert attempt.applicable is False
    assert attempt.result is None
    assert attempt.reason == "no_requested_plan_change"


def test_planning_runtime_attempt_marks_plan_patch_as_applicable(monkeypatch) -> None:
    def fake_decide_plan_change(requested_change, **kwargs):
        return SimpleNamespace(kind="block", reason="blocked")

    monkeypatch.setattr(
        "fitmas.legacy.planning_runtime_adapter.decide_plan_change",
        fake_decide_plan_change,
    )

    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision=_plan_patch_decision(),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert attempt.applicable is True
    assert attempt.result is not None
```

- [ ] **Step 2: Run the test and verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8b_planning_cutover.py::test_planning_runtime_attempt_marks_non_planning_as_not_applicable
```

Expected:

```text
ImportError: cannot import name 'run_planning_runtime_attempt_from_legacy_decision'
```

- [ ] **Step 3: Implement the attempt object**

In `backend/src/fitmas/legacy/planning_runtime_adapter.py`, add:

```python
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class PlanningRuntimeAdapterAttempt:
    applicable: bool
    result: PlanningDecisionResult | None
    reason: str
```

Replace the current body of `maybe_run_planning_runtime_from_legacy_decision`
with this wrapper:

```python
def maybe_run_planning_runtime_from_legacy_decision(
    *,
    decision: Any,
    context: Any,
    db: Session,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningDecisionResult | None:
    return run_planning_runtime_attempt_from_legacy_decision(
        decision=decision,
        context=context,
        db=db,
        user=user,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    ).result
```

Add the new function with the old logic:

```python
def run_planning_runtime_attempt_from_legacy_decision(
    *,
    decision: Any,
    context: Any,
    db: Session,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningRuntimeAdapterAttempt:
    understanding = coach_decision_to_understanding(decision)
    if understanding.requested_change is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="no_requested_plan_change",
        )

    planning_decision = decide_plan_change(
        understanding.requested_change,
        context=context,
        db=db,
        user=user,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if not isinstance(planning_decision, PlanningDecisionResult):
        return PlanningRuntimeAdapterAttempt(
            applicable=True,
            result=planning_decision,
            reason="non_standard_planning_result",
        )

    command_result = PlanningCommandService(db=db, user=user).apply(
        planning_decision,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        activities=tuple(getattr(getattr(context, "execution", None), "activities", ()) or ()),
        active_facts=tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ()),
    )
    return PlanningRuntimeAdapterAttempt(
        applicable=True,
        result=replace(
            planning_decision,
            command_result=command_result,
            pending_confirmation_id=command_result.pending_confirmation_id,
        ),
        reason="handled",
    )
```

Keep imports inside `legacy/`. Do not import this adapter from `decision/`.

- [ ] **Step 4: Run adapter tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_phase8b_planning_cutover.py
```

Expected:

```text
all passed
```

## Task 3 — Extract Conversation Planning Cutover Helper

**Files:**

- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `tests/test_phase8b_planning_cutover.py`

- [ ] **Step 1: Write failing tests for the helper**

Add to `tests/test_phase8b_planning_cutover.py`:

```python
from fitmas import conversation_pipeline
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult


def _planning_result(kind: str = "block") -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,  # type: ignore[arg-type]
        selected_candidate_id=None,
        candidate_options=(),
        reason="runtime handled",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=PlanningCommandResult(
            status="blocked",
            event_count=0,
            pending_confirmation_id=None,
            service_result=None,
            payload={"reason": "runtime handled"},
        ),
        pending_confirmation_id=None,
    )


def test_cutover_helper_uses_runtime_attempt_when_flag_on(monkeypatch) -> None:
    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(applicable=True, result=_planning_result(), reason="handled")

    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")
    monkeypatch.setattr(conversation_pipeline, "run_planning_runtime_attempt_from_legacy_decision", fake_attempt)

    outcome = conversation_pipeline._maybe_handle_planning_runtime_cutover(
        decision=_plan_patch_decision(),
        state=SimpleNamespace(scheduled_sessions=(), activities=(), active_facts=()),
        conversation_context=SimpleNamespace(
            temporal_resolution=SimpleNamespace(local_date=__import__("datetime").date(2026, 5, 14))
        ),
        coach_bundle=SimpleNamespace(coach_reading=""),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        source_text="deplace",
        reviewer_request_json_fn=None,
        grounding_facts=(),
    )

    assert calls
    assert outcome is not None
    assert outcome.response_mode == "planning_runtime_block"


def test_cutover_helper_blocks_applicable_unhandled_change(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")
    monkeypatch.setattr(
        conversation_pipeline,
        "run_planning_runtime_attempt_from_legacy_decision",
        lambda **kwargs: SimpleNamespace(applicable=True, result=None, reason="adapter_failed"),
    )

    outcome = conversation_pipeline._maybe_handle_planning_runtime_cutover(
        decision=_plan_patch_decision(),
        state=SimpleNamespace(scheduled_sessions=(), activities=(), active_facts=()),
        conversation_context=SimpleNamespace(
            temporal_resolution=SimpleNamespace(local_date=__import__("datetime").date(2026, 5, 14))
        ),
        coach_bundle=SimpleNamespace(coach_reading=""),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        source_text="deplace",
        reviewer_request_json_fn=None,
        grounding_facts=(),
    )

    assert outcome is not None
    assert outcome.response_mode == "planning_runtime_unhandled"
    assert outcome.mutation_applied is False
```

- [ ] **Step 2: Run and verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8b_planning_cutover.py
```

Expected:

```text
AttributeError: conversation_pipeline has no _maybe_handle_planning_runtime_cutover
```

- [ ] **Step 3: Implement the helper**

In `backend/src/fitmas/conversation_pipeline.py`, import:

```python
from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision
```

Add helper near `_conversation_outcome_from_planning_runtime_result`:

```python
def _maybe_handle_planning_runtime_cutover(
    *,
    decision,
    state,
    conversation_context,
    coach_bundle,
    db,
    user,
    source_text: str,
    reviewer_request_json_fn,
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    if not _planning_runtime_cutover_enabled():
        return None
    planning_context = _planning_context_from_turn_state(
        state=state,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
    )
    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision=decision,
        context=planning_context,
        db=db,
        user=user,
        source_text=source_text,
        coach_state_bundle=coach_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if attempt.result is not None:
        return _conversation_outcome_from_planning_runtime_result(
            attempt.result,
            user_text=source_text,
            grounding_facts=grounding_facts,
        )
    if attempt.applicable:
        return _planning_runtime_unhandled_outcome(reason=attempt.reason)
    return None
```

Add `_planning_runtime_unhandled_outcome` using `DecisionOutcome` and
`DecisionReplyComposer`; do not create a new local reply composer.

- [ ] **Step 4: Replace the inline flag block**

Replace the current inline block that starts with this exact condition:

```python
if outcome is None and decision is not None and _planning_runtime_cutover_enabled():
```

Use this call instead:

```python
if outcome is None and decision is not None:
    outcome = _maybe_handle_planning_runtime_cutover(
        decision=decision,
        state=state,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        db=db,
        user=user,
        source_text=payload.text,
        reviewer_request_json_fn=gw.request_json,
        grounding_facts=render_grounding_packet_for_prompt(grounding_packet),
    )
    if outcome is not None:
        decision = None
```

- [ ] **Step 5: Run planning cutover tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_planning_runtime_reply_composer.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_phase8b_planning_cutover.py
```

Expected:

```text
all passed
```

## Task 4 — Prove Legacy Planning Branches Are Skipped Under Flag-On

**Files:**

- Modify: `tests/test_phase8b_planning_cutover.py`

- [ ] **Step 1: Add branch-skip test**

Add a test that monkeypatches `_maybe_handle_plan_adaptation_candidates` to
raise if called after the runtime helper returns an outcome.

```python
def test_flag_on_runtime_outcome_prevents_mixed_legacy_adaptation_branch(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy mixed adaptation branch should not run after runtime outcome")

    monkeypatch.setattr(conversation_pipeline, "_maybe_handle_plan_adaptation_candidates", forbidden)
    monkeypatch.setattr(
        conversation_pipeline,
        "_maybe_handle_planning_runtime_cutover",
        lambda **kwargs: SimpleNamespace(
            extraction=conversation_pipeline.Extraction(confidence=0.85),
            reply_text="Runtime block.",
            response_mode="planning_runtime_block",
            mutation_applied=False,
            pending_confirmation=False,
            pending_confirmation_id=None,
        ),
    )

    # Keep this as a helper-level/unit test unless a stable full-turn fixture
    # already exists. The purpose is to lock branch order, not LLM behavior.
```

If full-turn fixtures are too expensive, do not force them here. Use helper
tests around branch ordering and keep real behavior to smoke gates.

- [ ] **Step 2: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_phase8b_planning_cutover.py
```

Expected:

```text
all passed
```

## Task 5 — Heartbeat Cutover Parity Tests

**Files:**

- Create: `tests/test_phase8b_heartbeat_cutover.py`
- Modify: `backend/src/fitmas/app/telegram/scheduler.py` only if needed

- [ ] **Step 1: Write tests for flag-on metadata and enforcement**

Create `tests/test_phase8b_heartbeat_cutover.py`:

```python
from __future__ import annotations

from fitmas.coach_messages import CoachDraft
from fitmas.legacy.heartbeat_runtime_adapter import HeartbeatRuntimeResult, run_heartbeat_trigger


def test_scheduler_cutover_passes_verify_enforcement_and_window_metadata(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.legacy.heartbeat_runtime_adapter as adapter

    draft = CoachDraft(text="Briefing propre.", proactive=True)
    calls = []

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        calls.append(kwargs)
        return run_heartbeat_trigger(**kwargs)

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "1")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory(
        "morning_briefing",
        lambda: draft,
        metadata={"window_status": "catchup"},
    )

    assert factory() is draft
    assert calls[0]["enforce_verifier"] is True
    assert calls[0]["metadata"] == {"window_status": "catchup"}


def test_scheduler_cutover_suppresses_blocked_draft(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.legacy.heartbeat_runtime_adapter as adapter

    draft = CoachDraft(text="Je deplace ta seance.", proactive=True)

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        result = run_heartbeat_trigger(**kwargs)
        return HeartbeatRuntimeResult(
            event=result.event,
            outcome=result.outcome,
            draft=None,
            reply_text=None,
            verifier_reason="plan_committed_without_event",
        )

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "1")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory("signal_check", lambda: draft)

    assert factory() is None
```

- [ ] **Step 2: Run heartbeat tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_heartbeat_runtime_adapter.py \
  tests/test_telegram_scheduler_runtime_adapter.py \
  tests/test_phase8b_heartbeat_cutover.py
```

Expected:

```text
all passed
```

## Task 6 — Add Architecture Gate For 8B Scope

**Files:**

- Modify: `tests/test_phase8a_legacy_audit.py` or create `tests/test_phase8b_cutover_architecture.py`

- [ ] **Step 1: Add architecture assertions**

Prefer a new file `tests/test_phase8b_cutover_architecture.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def test_phase8b_does_not_enable_cutover_flags_by_default() -> None:
    sources = [
        SRC / "conversation_pipeline.py",
        SRC / "legacy" / "heartbeat_runtime_adapter.py",
        SRC / "app" / "telegram" / "scheduler.py",
    ]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        assert "os.environ[\"FITMAS_PLANNING_RUNTIME_CUTOVER\"] = \"1\"" not in source
        assert "os.environ[\"FITMAS_HEARTBEAT_RUNTIME_CUTOVER\"] = \"1\"" not in source
        assert "os.environ[\"FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE\"] = \"1\"" not in source


def test_phase8b_decision_package_stays_free_of_legacy_adapters() -> None:
    decision_dir = SRC / "decision"
    offenders = []
    for path in sorted(decision_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy" in source or "conversation_pipeline" in source:
            offenders.append(path.name)
    assert offenders == []
```

- [ ] **Step 2: Run architecture gates**

Run:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py
```

Expected:

```text
all passed
```

## Task 7 — Run Flag-On Unit Gate

**Files:**

- No code edits.

- [ ] **Step 1: Run unit tests under cutover env**

Run:

```bash
FITMAS_PLANNING_RUNTIME_CUTOVER=1 \
FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1 \
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1 \
./scripts/test-backend -q \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_conversation_planning_runtime_reply_composer.py \
  tests/test_phase8b_planning_cutover.py \
  tests/test_heartbeat_runtime_adapter.py \
  tests/test_telegram_scheduler_runtime_adapter.py \
  tests/test_phase8b_heartbeat_cutover.py
```

Expected:

```text
all passed
```

## Task 8 — Run Real Cutover Smokes

**Files:**

- No code edits unless smokes expose a real bug.

- [ ] **Step 1: Run the harness**

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
unit gates pass
heartbeat_non_completion exits 0
compound_non_completion_swap exits 0
golden_case_autonomy exits 0
today_unavailability exits 0
move_easy_then_confirm exits 0
```

- [ ] **Step 2: If a smoke fails, classify the failure**

Use this mapping:

```text
wrong intent/signals      -> Understanding / legacy adapter
unresolved session/date   -> domain/planning/reference_resolver.py
bad candidate             -> domain/planning/candidate_builder.py
bad commit/pending/block  -> domain/planning/policy.py or mutation_service.py
claim without event       -> decision/output_verifier.py or legacy reply bridge
heartbeat send/no_send    -> legacy/heartbeat_runtime_adapter.py or app/telegram/scheduler.py
```

Do not add prompt rules or local fallbacks as first response.

## Task 9 — Update Docs With Evidence

**Files:**

- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Record 8B status**

Add a Phase 8B section to the refactor doc:

```text
Livres en Phase 8B :
- cutover harness `scripts/smoke-decision-runtime-cutover`
- planning runtime attempt object
- conversation flag-on strict runtime route
- heartbeat flag-on enforcement tests
- no default cutover

Verification Phase 8B :
- `./scripts/test-backend -q tests/test_phase8b_cutover_harness.py tests/test_phase8b_planning_cutover.py tests/test_phase8b_heartbeat_cutover.py tests/test_phase8b_cutover_architecture.py`
- `FITMAS_PLANNING_RUNTIME_CUTOVER=1 FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1 FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1 ./scripts/test-backend -q tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase8b_planning_cutover.py tests/test_heartbeat_runtime_adapter.py tests/test_telegram_scheduler_runtime_adapter.py tests/test_phase8b_heartbeat_cutover.py`
- `./scripts/smoke-decision-runtime-cutover`
```

- [ ] **Step 2: Update the kill list**

In `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`, mark:

```text
Phase 8B result:
- planning/heartbeat cutovers have evidence under flags
- legacy still present physically
- 8C may start removing specific active routes
```

- [ ] **Step 3: Update Build Order**

In `docs/BUILD-ORDER.md`, add Phase 8B local status and next step:

```text
Next:
Phase 8C1 remove direct conversation planning legacy branch after flag-on parity.
```

## Acceptance Criteria

Phase 8B is done only when all are true:

```text
1. Flag-off behavior remains unchanged by tests.
2. Flag-on planning uses runtime attempt object.
3. Applicable but unhandled planning changes become safe runtime blocks, not legacy fallthrough.
4. Heartbeat scheduler/manual/debug/ops can run through runtime adapter under flags.
5. Cutover harness exists and documents the real smoke battery.
6. Architecture tests prove decision/ remains free of legacy adapters.
7. Docs record exact evidence.
```

Minimum verification:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase7_heartbeat_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_harness.py \
  tests/test_phase8b_planning_cutover.py \
  tests/test_phase8b_heartbeat_cutover.py \
  tests/test_phase8b_cutover_architecture.py
```

Flag-on verification:

```bash
FITMAS_PLANNING_RUNTIME_CUTOVER=1 \
FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1 \
FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1 \
./scripts/test-backend -q \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_conversation_planning_runtime_reply_composer.py \
  tests/test_phase8b_planning_cutover.py \
  tests/test_heartbeat_runtime_adapter.py \
  tests/test_telegram_scheduler_runtime_adapter.py \
  tests/test_phase8b_heartbeat_cutover.py
```

Real smoke verification:

```bash
./scripts/smoke-decision-runtime-cutover
```

Full backend verification if code paths beyond docs/tests changed materially:

```bash
./scripts/test-backend -q
```

## Phase 8C Handoff

Do not start 8C until 8B has real evidence.

8C should then remove one active route at a time:

```text
8C1 remove direct conversation planning legacy fallthrough
8C2 remove direct final_reply callers from conversation/heartbeat active paths
8C3 isolate WeeklyPlan/DayPlan runtime reads
8C4 remove tools compat from active LLM registry
8C5 archive or delete MutationDecision runtime support
```

If 8B reveals that flag-on parity is not stable, do not delete. Fix the responsible layer first.
