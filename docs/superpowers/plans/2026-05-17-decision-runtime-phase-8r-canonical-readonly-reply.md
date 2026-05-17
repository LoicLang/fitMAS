---
summary: implementation plan for Decision Runtime Phase 8R canonical read-only reply pivot
read_when:
  - implementing Decision Runtime Phase 8R
  - skipping legacy CoachDecision for plan lookup or read-only answer lanes
  - changing conversation_pipeline.py around canonical reply outcomes
  - debugging FITMAS_CANONICAL_READONLY_PROVIDER
---

# Decision Runtime Phase 8R Canonical Read-Only Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let canonical `CoachUnderstanding` skip legacy `decide()` for safe read-only answer lanes by producing a `DecisionOutcome(kind="answer")` and composing through the existing Decision ReplyComposer boundary.

**Architecture:** Phase 8Q removed `decide()` from non-planning actionable lanes. Phase 8R removes it from read-only truth lanes behind a dedicated flag; Phase 8S promotes that flag to default-on after deterministic gates. The LLM still understands user intent; backend creates an answer outcome; ReplyComposer is the only speech boundary; legacy `CoachDecision` remains fallback for planning, pending, action lanes and any unsupported read-only lane.

**Tech Stack:** Python, pytest, existing `fitmas.decision` dataclasses, `DecisionReplyComposer`, `LegacyFinalReplyBackend`, conversation legacy bridges.

---

## CTO Decision

Do **not** attack planning next.

Reason:

```text
Planning fallback still carries write/pending risk.
Read-only lanes carry speech risk only.
Speech risk is easier to flag, test, dogfood and roll back.
```

So 8R should cut `decide()` from:

```text
plan_lookup
fact_recall / truth read
general_answer grounded by context
```

8R should **not** cut:

```text
plan_change
requested_change
active pending
commands from Understanding
close_turn / no_send terminal acks
```

Close/no-send gets its own later slice because it affects delivery behavior,
not just reply generation.

## File Structure

**Create**

- `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py`
  - owns the 8R flag;
  - decides whether a canonical read-only turn may skip legacy;
  - builds `DecisionOutcome(kind="answer")`;
  - composes via `DecisionReplyComposer(LegacyFinalReplyBackend)`;
  - records trace payloads.

- `tests/test_conversation_canonical_readonly_bridge.py`
  - unit tests for gate, outcome and composer wiring.

- `tests/test_phase8r_canonical_readonly_architecture.py`
  - static architecture tests around pipeline ordering and wrapper content.

- `scripts/smoke-decision-runtime-canonical-readonly`
  - deterministic wrapper only.

**Modify**

- `backend/src/fitmas/conversation_pipeline.py`
  - after 8Q actionable canonical check, before `run_legacy_coach_decision(...)`,
    call the read-only bridge.

- `docs/DECISION-RUNTIME-REFACTOR.md`
  - add Phase 8R result and debt.

- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
  - add flag and remaining fallback surfaces.

- `docs/BUILD-ORDER.md`
  - add local status once verified.

## Invariants

```text
1. No deterministic parsing of free user text.
2. No writes.
3. No PlanPatch.
4. No pending resolution.
5. No commands.
6. No visible reply outside ReplyComposer.
7. Legacy CoachDecision remains fallback.
8. 8R introduces a rollback flag; 8S makes it default-on with opt-out.
```

## Task 1: Add The Read-Only Gate

**Files:**
- Create: `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py`
- Test: `tests/test_conversation_canonical_readonly_bridge.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange, UserSignal
from fitmas.legacy import conversation_canonical_readonly_bridge as bridge


def _understanding(intent: str = "plan_lookup", *, requested_change=None, signals=()):
    return CoachUnderstanding(
        intent=intent,
        confidence=0.9,
        user_summary="Demande de lecture du plan.",
        extracted_signals=tuple(signals),
        requested_change=requested_change,
        pending_resolution=None,
        clarification_need=None,
    )


def test_readonly_provider_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    assert bridge.canonical_readonly_provider_enabled() is False


def test_readonly_gate_accepts_plan_lookup_when_flag_on(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "1")

    assert bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding("plan_lookup"),
        turn_plan=SimpleNamespace(
            primary_intent="plan_lookup",
            secondary_intents=(),
            requires_truth_read=True,
            truth_scope="plan_window",
        ),
        pending_confirmation=None,
    )


def test_readonly_gate_rejects_planning(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "1")

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding(
            "plan_change",
            requested_change=RequestedPlanChange(
                kind="move",
                source_ref="demain",
                target_ref="vendredi",
                desired_sport=None,
                desired_duration_min=None,
                desired_intensity=None,
                reason="demande user",
                risk_signals=(),
            ),
        ),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=()),
        pending_confirmation=None,
    )


def test_readonly_gate_rejects_active_pending(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "1")

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding("plan_lookup"),
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=()),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_readonly_gate_rejects_command_signals(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "1")

    signal = UserSignal(
        type="availability",
        label="piscine fermee",
        status="unavailable",
        severity="unknown",
        confidence=0.9,
        evidence="piscine fermee",
        payload={
            "action_type": "record_availability",
            "availability": "unavailable",
            "sport_type": "swimming",
        },
    )

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding("availability_signal", signals=(signal,)),
        turn_plan=SimpleNamespace(primary_intent="availability_constraint", secondary_intents=()),
        pending_confirmation=None,
    )
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_readonly_bridge.py
```

Expected:

```text
ModuleNotFoundError or AttributeError for conversation_canonical_readonly_bridge
```

- [ ] **Step 3: Implement minimal gate**

Create `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py`:

```python
from __future__ import annotations

import os
from typing import Any

from fitmas.decision import CoachUnderstanding
from fitmas.legacy.coach_command_adapter import commands_from_understanding

_READONLY_INTENTS = {
    "plan_lookup",
    "general_answer",
    "fact_recall",
}


def canonical_readonly_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_READONLY_PROVIDER", default=False)


def should_use_canonical_readonly_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_readonly_provider_enabled():
        return False
    if understanding is None:
        return False
    if understanding.intent == "plan_change" or understanding.requested_change is not None:
        return False
    if _has_active_pending(pending_confirmation):
        return False
    if commands_from_understanding(understanding).commands:
        return False
    return _turn_plan_is_readonly_answer(turn_plan) or understanding.intent in _READONLY_INTENTS


def _turn_plan_is_readonly_answer(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent in _READONLY_INTENTS:
        return True
    if bool(getattr(turn_plan, "requires_truth_read", False)):
        return primary_intent not in {"plan_mutation", "availability_constraint", "health_signal", "execution_report"}
    return False


def _has_active_pending(pending_confirmation: Any) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_readonly_bridge.py
```

Expected:

```text
5 passed
```

## Task 2: Build Answer Outcome Through ReplyComposer

**Files:**
- Modify: `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py`
- Test: `tests/test_conversation_canonical_readonly_bridge.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from fitmas.decision import DecisionOutcome


class FakeComposer:
    def compose(self, outcome, context, *, user_text="", grounding_facts=()):
        assert outcome.kind == "answer"
        assert outcome.commands == ()
        assert outcome.applied_commands == ()
        assert "mutation_committed" not in outcome.reply_contract.allowed_claims
        assert grounding_facts == ("Demain: endurance 45min",)
        return SimpleNamespace(text="Demain, endurance 45 minutes.", verified=True, fallback_used=False, reason=None)


def test_compose_canonical_readonly_outcome_returns_conversation_outcome(monkeypatch):
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "1")

    outcome = bridge.compose_canonical_readonly_reply(
        composer=FakeComposer(),
        understanding=_understanding("plan_lookup"),
        user_text="c'est quoi demain ?",
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=()),
        turn_context={},
        grounding_facts=("Demain: endurance 45min",),
    )

    assert outcome is not None
    assert outcome.reply_text == "Demain, endurance 45 minutes."
    assert outcome.response_mode == "canonical_readonly_answer"
    assert outcome.mutation_applied is False
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_readonly_bridge.py::test_compose_canonical_readonly_outcome_returns_conversation_outcome
```

Expected:

```text
AttributeError: module ... has no attribute compose_canonical_readonly_reply
```

- [ ] **Step 3: Implement outcome composer**

Extend bridge with:

```python
from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.models import Extraction


def compose_canonical_readonly_reply(
    *,
    composer,
    understanding: CoachUnderstanding,
    user_text: str,
    turn_plan: Any,
    turn_context: dict[str, object],
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    outcome = _answer_outcome_from_understanding(understanding, turn_plan=turn_plan)
    result = composer.compose(
        outcome,
        None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    if result is None or not getattr(result, "text", None):
        return None
    turn_context["canonical_readonly_reply"] = {
        "intent": understanding.intent,
        "source": "coach_understanding",
        "composed": True,
        "verified": bool(getattr(result, "verified", False)),
        "fallback_used": bool(getattr(result, "fallback_used", False)),
    }
    turn_context["legacy_decide"] = {
        "source": "coach_understanding_readonly",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_readonly_answer",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=understanding.confidence),
        reply_text=str(result.text),
        response_mode="canonical_readonly_answer",
        decision=None,
        mutation_applied=False,
    )


def _answer_outcome_from_understanding(
    understanding: CoachUnderstanding,
    *,
    turn_plan: Any,
) -> DecisionOutcome:
    reason = understanding.user_summary or "Reponse basee sur le contexte disponible."
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=primary_intent or understanding.intent or "answer",
            reason_summary=reason,
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_readonly_answer",
            audience="user",
            allowed_claims=("read_truth", "answer"),
            forbidden_claims=("mutation_committed", "pending_created", "plan_changed"),
        ),
    )
```

- [ ] **Step 4: Verify green**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_readonly_bridge.py
```

Expected:

```text
6 passed
```

## Task 3: Wire Pipeline Before Legacy Decide

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_phase8r_canonical_readonly_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_8r_canonical_readonly_bridge_exists():
    source = _source("legacy/conversation_canonical_readonly_bridge.py")

    assert "def canonical_readonly_provider_enabled(" in source
    assert "FITMAS_CANONICAL_READONLY_PROVIDER" in source
    assert "def should_use_canonical_readonly_without_legacy(" in source
    assert "def compose_canonical_readonly_reply(" in source
    assert "DecisionOutcome(" in source
    assert "DecisionReplyComposer" not in source


def test_8r_pipeline_routes_readonly_before_legacy_decide():
    source = _source("conversation_pipeline.py")

    readonly_index = source.index("should_use_canonical_readonly_without_legacy(")
    legacy_index = source.index("run_legacy_coach_decision(")
    assert readonly_index < legacy_index
    assert "compose_canonical_readonly_reply(" in source


def test_8r_smoke_wrapper_is_deterministic_only():
    source = (SCRIPTS / "smoke-decision-runtime-canonical-readonly").read_text(encoding="utf-8")

    assert "tests/test_phase8r_canonical_readonly_architecture.py" in source
    assert "tests/test_conversation_canonical_readonly_bridge.py" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
```

- [ ] **Step 2: Verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8r_canonical_readonly_architecture.py
```

Expected:

```text
fail because pipeline does not call canonical readonly bridge and wrapper is missing
```

- [ ] **Step 3: Wire pipeline**

Modify imports in `conversation_pipeline.py`:

```python
from fitmas.legacy import conversation_canonical_readonly_bridge
```

After the 8Q actionable canonical branch and before `run_legacy_coach_decision(...)`, add:

```python
        elif conversation_canonical_readonly_bridge.should_use_canonical_readonly_without_legacy(
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ):
            composer = DecisionReplyComposer(reply_backend=LegacyFinalReplyBackend())
            outcome = conversation_canonical_readonly_bridge.compose_canonical_readonly_reply(
                composer=composer,
                understanding=canonical_understanding,
                user_text=payload.text,
                turn_plan=turn_plan,
                turn_context=turn_context,
                grounding_facts=tuple(render_grounding_packet_for_prompt(grounding_packet).splitlines()),
            )
            legacy_decision_artifact = None
        else:
            legacy_decision_artifact = conversation_decide_bridge.run_legacy_coach_decision(...)
```

Keep the exact surrounding control flow adapted to the current pipeline shape:
`outcome` must be set before action/pending/planning branches, and
`legacy_decision_artifact` must stay `None` when the canonical read-only branch
handled the turn.

- [ ] **Step 4: Verify architecture green**

Run:

```bash
./scripts/test-backend -q tests/test_phase8r_canonical_readonly_architecture.py
```

Expected:

```text
3 passed
```

## Task 4: Add Smoke Wrapper

**Files:**
- Create: `scripts/smoke-decision-runtime-canonical-readonly`
- Modify: executable bit

- [ ] **Step 1: Create wrapper**

```bash
#!/usr/bin/env bash
set -euo pipefail

./scripts/test-backend -q \
  tests/test_phase8r_canonical_readonly_architecture.py \
  tests/test_conversation_canonical_readonly_bridge.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_coach_decision_reply_bridge.py

./scripts/smoke-decision-runtime-canonical-provider-pivot

echo "RESULT: OK"
```

- [ ] **Step 2: Make executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-canonical-readonly
```

- [ ] **Step 3: Verify wrapper**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-readonly
```

Expected:

```text
RESULT: OK
```

## Task 5: Verification And Docs

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Run targeted regressions**

```bash
./scripts/test-backend -q \
  tests/test_conversation_canonical_readonly_bridge.py \
  tests/test_phase8r_canonical_readonly_architecture.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_core_flows.py
```

Expected:

```text
all passed
```

- [ ] **Step 2: Run Phase 8 architecture pack**

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
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_phase8n_provider_tool_loop_architecture.py \
  tests/test_phase8o_coachdecision_artifact_architecture.py \
  tests/test_phase8p_decision_legacy_support_split_architecture.py \
  tests/test_phase8q_canonical_provider_pivot_architecture.py \
  tests/test_phase8r_canonical_readonly_architecture.py
```

Expected:

```text
all passed
```

- [ ] **Step 3: Run full backend**

```bash
./scripts/test-backend
```

Expected:

```text
all passed, skipped integration tests unchanged
```

- [ ] **Step 4: Run diff check**

```bash
git diff --check
```

Expected:

```text
exit 0
```

- [ ] **Step 5: Update docs with exact verification counts**

Document:

```text
Phase 8R delivered:
- canonical read-only provider flag exists, default-off
- plan_lookup/truth-read can skip CoachDecision under flag
- replies are composed from DecisionOutcome via ReplyComposer
- planning, pending, commands and close_turn remain fallback
- smoke wrapper deterministic only
- full backend result
```

## Acceptance Criteria

```text
With FITMAS_CANONICAL_READONLY_PROVIDER=1:
- supported read-only truth lanes skip legacy decide()
- ReplyComposer produces the visible answer from DecisionOutcome
- no writes occur
- no PlanPatch/pending/action command is accepted on this path

With default flags:
- behavior remains conservative
- CoachDecision fallback still handles read-only replies
```

## Next Slices After 8R

```text
8S: Dogfood/default-enable canonical read-only provider if 8R is stable.
8T: Planning canonical cutover hardening, probably the next big risky slice.
8U: Delete or quarantine more CoachDecision provider fallback once planning is safe.
```
