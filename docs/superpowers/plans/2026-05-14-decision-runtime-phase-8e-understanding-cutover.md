---
summary: implementation plan for Decision Runtime Phase 8E canonical Understanding cutover
read_when:
  - implementing Decision Runtime Phase 8E
  - cutting conversation understanding away from CoachDecision
  - adding LLMUnderstandingService or canonical CoachUnderstanding parsing
  - routing planning runtime from canonical RequestedPlanChange
  - shrinking conversation_pipeline.py after Phase 8D
---

# Decision Runtime Phase 8E Understanding Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a canonical `LLMUnderstandingService` and make `CoachUnderstanding` available to the conversation runtime before legacy `CoachDecision`, without allowing Understanding to write, speak, or emit `PlanPatch`.

**Architecture:** 8E is a cutover preparation slice, not the final deletion of `CoachDecision`. The new LLM Understanding service lives under `fitmas.llm`, parses strict `CoachUnderstanding`, and is invoked from a legacy conversation bridge behind flags. Planning can consume canonical `RequestedPlanChange` when present; legacy `CoachDecision` remains fallback until parity is proven.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing `fitmas.llm.gateway.request_json`, canonical prompts under `fitmas.llm.prompts`, existing `DecisionRuntimeService`, architecture tests.

---

## CTO Decision

Do **not** fully replace `dependencies.decide(...)` in 8E.

The repo is not ready for a single-step swap because `CoachDecision` still carries:

```text
- memory_actions
- execution_actions
- pending_resolution
- legacy fitmas_message
- old tests and monkeypatch surface
```

8E should move product understanding authority one level earlier:

```text
InputEvent + compact context
-> LLMUnderstandingService
-> CoachUnderstanding
-> turn_context["canonical_understanding"]
-> planning runtime can use requested_change directly
-> legacy CoachDecision remains fallback for actions/reply until 8F/8G
```

Risk trade-off:

- **Too aggressive:** remove `CoachDecision` now. High risk: memory/execution/pending flows regress.
- **Too timid:** only add another shadow log. Low value: `CoachDecision` stays the source of meaning.
- **Recommended:** canonical Understanding service + opt-in LLM shadow + planning adapter consumes canonical `RequestedPlanChange` when present. This creates a real migration surface without breaking dogfood.

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. Understanding cannot write.
3. Understanding cannot speak to the user.
4. Understanding cannot emit PlanPatch, MutationDecision, CoachDecision or commands.
5. decision/ must not import llm/, legacy/, DB, tools or conversation_pipeline.
6. conversation_pipeline.py must not grow new decision branches.
7. Any canonical understanding call must be behind an explicit flag in 8E.
8. Existing dogfood behavior must remain unchanged when flags are off.
9. Planning runtime may consume canonical RequestedPlanChange only through the existing candidate/policy path.
10. Every new bridge lives in legacy/ until conversation_pipeline is a thin adapter.
```

## Flags

Add two flags.

```text
FITMAS_UNDERSTANDING_RUNTIME_SHADOW
  default: off
  effect: call canonical LLM Understanding before legacy decide and store result in turn_context

FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER
  default: off
  effect: planning runtime adapter uses canonical RequestedPlanChange when available
```

Do not use these flags to produce a visible reply directly in 8E.

## File Map

Create:

```text
backend/src/fitmas/llm/understanding_service.py
backend/src/fitmas/legacy/conversation_understanding_bridge.py
tests/test_llm_understanding_service.py
tests/test_conversation_understanding_bridge.py
tests/test_phase8e_understanding_cutover_architecture.py
```

Modify:

```text
backend/src/fitmas/llm/prompts/understanding.py
backend/src/fitmas/legacy/planning_runtime_adapter.py
backend/src/fitmas/legacy/conversation_planning_bridge.py
backend/src/fitmas/conversation_pipeline.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify unless a failing test proves it is necessary:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/tools/registry.py
backend/src/fitmas/plan_mutation_service.py
```

## Task 1 — 8E Architecture Gates

**Files:**

- Create: `tests/test_phase8e_understanding_cutover_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create `tests/test_phase8e_understanding_cutover_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    path = SRC / relative
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8e_llm_understanding_service_exists_without_legacy_contracts() -> None:
    source = _source("llm/understanding_service.py")
    imports = _imports("llm/understanding_service.py")

    assert "class LLMUnderstandingService" in source
    assert "parse_coach_understanding_payload" in source
    assert "fitmas.decision" in imports
    assert "fitmas.llm.prompts.understanding" in imports
    assert "fitmas.llm.gateway" in imports
    assert "fitmas.llm.decision_legacy" not in imports
    assert "fitmas.legacy" not in imports
    assert "fitmas.conversation_pipeline" not in imports
    assert "PlanPatch" not in source
    assert "MutationDecision" not in source
    assert "fitmas_message" not in source
    assert "reply_text" not in source


def test_8e_conversation_uses_understanding_bridge_not_direct_llm_service() -> None:
    source = _source("conversation_pipeline.py")

    assert "conversation_understanding_bridge" in source
    assert "LLMUnderstandingService" not in source
    assert "build_understanding_prompt" not in source
    assert "canonical_understanding" in source


def test_8e_understanding_bridge_is_legacy_boundary() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" in source
    assert "run_canonical_understanding_shadow" in source
    assert "understanding_to_turn_context_payload" in source
    assert "from fitmas.llm.understanding_service import" in source


def test_8e_planning_runtime_accepts_canonical_understanding_input() -> None:
    adapter = _source("legacy/planning_runtime_adapter.py")
    bridge = _source("legacy/conversation_planning_bridge.py")

    assert "understanding: CoachUnderstanding | None" in adapter
    assert "if understanding is None" in adapter
    assert "understanding.requested_change" in adapter
    assert "canonical_understanding" in bridge


def test_8e_decision_package_still_has_no_llm_or_legacy_imports() -> None:
    offenders: list[str] = []
    for path in sorted((SRC / "decision").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("fitmas.llm", "fitmas.legacy", "fitmas.conversation_pipeline")):
                        offenders.append(f"{path.name}:{alias.name}")
                continue
            if module and module.startswith(("fitmas.llm", "fitmas.legacy", "fitmas.conversation_pipeline")):
                offenders.append(f"{path.name}:{module}")

    assert offenders == []


def test_8e_understanding_prompt_schema_matches_canonical_signal_types() -> None:
    source = _source("llm/prompts/understanding.py")

    assert "health | availability | preference | execution | readiness | planning | pending | other" in source
    assert "fatigue | pain | availability" not in source
    assert "accept_pending | reject_pending | modify_pending | ignore | needs_clarification" in source
```

- [ ] **Step 2: Run architecture tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_phase8e_understanding_cutover_architecture.py
```

Expected:

```text
FAIL FileNotFoundError: llm/understanding_service.py
FAIL FileNotFoundError: legacy/conversation_understanding_bridge.py
```

## Task 2 — Canonical Understanding Parser And Prompt Alignment

**Files:**

- Create: `backend/src/fitmas/llm/understanding_service.py`
- Modify: `backend/src/fitmas/llm/prompts/understanding.py`
- Create: `tests/test_llm_understanding_service.py`
- Test: `tests/test_llm_prompts_understanding.py`
- Test: `tests/test_phase6_prompt_architecture.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_llm_understanding_service.py`:

```python
from __future__ import annotations

from fitmas.decision import CoachUnderstanding
from fitmas.llm.understanding_service import (
    LLMUnderstandingService,
    UnderstandingRequest,
    parse_coach_understanding_payload,
)


def test_parse_coach_understanding_payload_accepts_minimal_answer() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_lookup",
            "confidence": 0.91,
            "user_summary": "demande le plan de demain",
            "extracted_signals": [],
            "requested_change": None,
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert isinstance(understanding, CoachUnderstanding)
    assert understanding.intent == "plan_lookup"
    assert understanding.confidence == 0.91
    assert understanding.extracted_signals == ()


def test_parse_coach_understanding_payload_accepts_requested_change_and_signal() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "veut deplacer la seance dure a vendredi",
            "extracted_signals": [
                {
                    "type": "readiness",
                    "label": "fatigue",
                    "status": "new",
                    "severity": "moderate",
                    "confidence": 0.8,
                    "evidence": "mal dormi",
                    "payload": {"affects": ["training_load"]},
                }
            ],
            "requested_change": {
                "kind": "move",
                "source_ref": "seance dure de ce soir",
                "target_ref": "vendredi",
                "desired_sport": None,
                "desired_duration_min": None,
                "desired_intensity": None,
                "reason": "fatigue",
                "risk_signals": ["fatigue"],
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding.intent == "plan_change"
    assert understanding.extracted_signals[0].type == "readiness"
    assert understanding.extracted_signals[0].payload["affects"] == ["training_load"]
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "move"
    assert understanding.requested_change.target_ref == "vendredi"


def test_parse_coach_understanding_payload_rejects_visible_reply_and_patch_fields() -> None:
    assert parse_coach_understanding_payload({"intent": "plan_lookup", "reply_text": "Salut"}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "fitmas_message": "Je bouge ca"}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "plan_patch": {"operations": []}}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "commands": []}) is None


def test_llm_understanding_service_calls_prompt_and_request_json() -> None:
    calls: list[dict] = []

    def fake_request_json(**kwargs):
        calls.append(kwargs)
        return {
            "intent": "general_answer",
            "confidence": 0.72,
            "user_summary": "question generale",
            "extracted_signals": [],
            "requested_change": None,
            "pending_resolution": None,
            "clarification_need": None,
        }

    service = LLMUnderstandingService(request_json_fn=fake_request_json)
    result = service.understand(
        UnderstandingRequest(
            event_summary="source=telegram type=user_message text=ok",
            context_blocks=("Plan compact: repos demain",),
        )
    )

    assert result is not None
    assert result.intent == "general_answer"
    assert calls
    assert calls[0]["schema_hint"] == "CoachUnderstanding"
    assert "Tu ne parles pas au user" in calls[0]["system"]
```

- [ ] **Step 2: Run parser tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_llm_understanding_service.py
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.llm.understanding_service'
```

- [ ] **Step 3: Implement service and parser**

Create `backend/src/fitmas/llm/understanding_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fitmas.decision import (
    ClarificationNeed,
    CoachUnderstanding,
    PendingResolution,
    RequestedPlanChange,
    UserSignal,
)
from fitmas.llm import gateway as gw
from fitmas.llm.prompts.understanding import UnderstandingPromptInput, build_understanding_prompt


FORBIDDEN_UNDERSTANDING_KEYS = {
    "reply_text",
    "final_reply",
    "fitmas_message",
    "coach_message",
    "plan_patch",
    "mutation_decision",
    "commands",
    "memory_actions",
    "execution_actions",
}


@dataclass(frozen=True, slots=True)
class UnderstandingRequest:
    event_summary: str
    context_blocks: tuple[str, ...]


class LLMUnderstandingService:
    def __init__(self, request_json_fn: Callable[..., dict | None] | None = None) -> None:
        self._request_json_fn = request_json_fn or gw.request_json

    def understand(self, request: UnderstandingRequest) -> CoachUnderstanding | None:
        rendered = build_understanding_prompt(
            UnderstandingPromptInput(
                event_summary=request.event_summary,
                context_blocks=request.context_blocks,
            )
        )
        payload = self._request_json_fn(
            system=rendered.system,
            prompt=rendered.prompt,
            max_tokens=rendered.max_tokens,
            schema_hint="CoachUnderstanding",
        )
        return parse_coach_understanding_payload(payload)


def parse_coach_understanding_payload(payload: Mapping[str, Any] | None) -> CoachUnderstanding | None:
    if not isinstance(payload, Mapping):
        return None
    if FORBIDDEN_UNDERSTANDING_KEYS.intersection(payload.keys()):
        return None
    try:
        return CoachUnderstanding(
            intent=str(payload.get("intent") or "general_answer"),
            confidence=_confidence(payload.get("confidence"), default=0.5),
            user_summary=str(payload.get("user_summary") or "").strip(),
            extracted_signals=_signals(payload.get("extracted_signals")),
            requested_change=_requested_change(payload.get("requested_change")),
            pending_resolution=_pending_resolution(payload.get("pending_resolution")),
            clarification_need=_clarification_need(payload.get("clarification_need")),
        )
    except (TypeError, ValueError):
        return None


def _signals(value: Any) -> tuple[UserSignal, ...]:
    if not isinstance(value, list | tuple):
        return ()
    signals: list[UserSignal] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        signal_type = str(item.get("type") or "other")
        if signal_type in {"fatigue", "pain"}:
            signal_type = "readiness" if signal_type == "fatigue" else "health"
        signals.append(
            UserSignal(
                type=signal_type,
                label=str(item.get("label") or item.get("type") or "other"),
                status=str(item.get("status") or "unknown"),
                severity=str(item.get("severity") or "unknown"),
                confidence=_confidence(item.get("confidence"), default=0.7),
                evidence=_optional_str(item.get("evidence")),
                payload=_mapping(item.get("payload")),
            )
        )
    return tuple(signals)


def _requested_change(value: Any) -> RequestedPlanChange | None:
    if not isinstance(value, Mapping):
        return None
    return RequestedPlanChange(
        kind=str(value.get("kind") or "unknown"),
        source_ref=_optional_str(value.get("source_ref")),
        target_ref=_optional_str(value.get("target_ref")),
        desired_sport=_optional_str(value.get("desired_sport")),
        desired_duration_min=_optional_int(value.get("desired_duration_min")),
        desired_intensity=_optional_str(value.get("desired_intensity")),
        reason=str(value.get("reason") or "").strip(),
        risk_signals=tuple(str(item) for item in value.get("risk_signals") or ()),
    )


def _pending_resolution(value: Any) -> PendingResolution | None:
    if not isinstance(value, Mapping):
        return None
    resolution_type = str(value.get("type") or "ignore")
    legacy_map = {
        "accept": "accept_pending",
        "reject": "reject_pending",
        "modify": "modify_pending",
    }
    return PendingResolution(
        type=legacy_map.get(resolution_type, resolution_type),
        reason=_optional_str(value.get("reason")),
        selected_candidate_id=_optional_str(value.get("selected_candidate_id")),
        requested_changes=_optional_str(value.get("requested_changes")),
        question=_optional_str(value.get("question")),
    )


def _clarification_need(value: Any) -> ClarificationNeed | None:
    if not isinstance(value, Mapping):
        return None
    question_intent = _optional_str(value.get("question_intent")) or _optional_str(value.get("question")) or "clarify"
    return ClarificationNeed(
        reason=str(value.get("reason") or value.get("question") or "").strip(),
        missing_fields=tuple(str(item) for item in value.get("missing_fields") or ()),
        question_intent=question_intent,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _confidence(value: Any, *, default: float) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return default
```

- [ ] **Step 4: Align understanding prompt schema**

Modify `backend/src/fitmas/llm/prompts/understanding.py`.

Change the `extracted_signals.type` schema line from:

```python
"type": "fatigue | pain | availability | preference | execution | other",
```

to:

```python
"type": "health | availability | preference | execution | readiness | planning | pending | other",
```

Change `pending_resolution.type` from:

```python
"type": "accept | reject | modify | ignore | needs_clarification",
```

to:

```python
"type": "accept_pending | reject_pending | modify_pending | ignore | needs_clarification",
```

- [ ] **Step 5: Run service and prompt tests**

Run:

```bash
./scripts/test-backend -q tests/test_llm_understanding_service.py tests/test_llm_prompts_understanding.py tests/test_phase6_prompt_architecture.py
```

Expected:

```text
PASS
```

## Task 3 — Conversation Understanding Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_understanding_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Create: `tests/test_conversation_understanding_bridge.py`
- Test: `tests/test_conversation_understanding_shadow.py`
- Test: `tests/test_core_flows.py`

- [ ] **Step 1: Write bridge tests**

Create `tests/test_conversation_understanding_bridge.py`:

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange
from fitmas.legacy import conversation_understanding_bridge as bridge


def _understanding() -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="plan_change",
        confidence=0.88,
        user_summary="deplacement demande",
        extracted_signals=(),
        requested_change=RequestedPlanChange(
            kind="move",
            source_ref="seance dure",
            target_ref="vendredi",
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity=None,
            reason="fatigue",
            risk_signals=("fatigue",),
        ),
        pending_resolution=None,
        clarification_need=None,
    )


def test_understanding_shadow_flag_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)

    assert bridge.understanding_runtime_shadow_enabled() is False


def test_planning_cutover_flag_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", raising=False)

    assert bridge.understanding_runtime_planning_cutover_enabled() is False


def test_understanding_to_turn_context_payload_is_safe() -> None:
    payload = bridge.understanding_to_turn_context_payload(_understanding())

    assert payload["intent"] == "plan_change"
    assert payload["requested_change"]["kind"] == "move"
    assert "fitmas_message" not in repr(payload)
    assert "plan_patch" not in repr(payload)


def test_run_canonical_understanding_shadow_skips_when_flag_off(monkeypatch) -> None:
    calls: list[str] = []

    class FakeService:
        def understand(self, request):
            calls.append(request.event_summary)
            return _understanding()

    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)

    result = bridge.run_canonical_understanding_shadow(
        service=FakeService(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        user_text="deplace vendredi",
        turn_plan=SimpleNamespace(primary_intent="plan_mutation"),
        conversation_context=SimpleNamespace(temporal_resolution=SimpleNamespace(local_date=date(2026, 5, 14))),
        coach_bundle=SimpleNamespace(week_summary="Semaine compacte", planning_context="Planning compact"),
        state=SimpleNamespace(scheduled_sessions=(), activities=(), active_facts=()),
        pending_confirmation=None,
        turn_context={},
    )

    assert result is None
    assert calls == []


def test_run_canonical_understanding_shadow_records_payload_when_flag_on(monkeypatch) -> None:
    calls: list[str] = []

    class FakeService:
        def understand(self, request):
            calls.append(request.event_summary)
            return _understanding()

    turn_context: dict[str, object] = {}
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", "1")

    result = bridge.run_canonical_understanding_shadow(
        service=FakeService(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        user_text="deplace vendredi",
        turn_plan=SimpleNamespace(primary_intent="plan_mutation"),
        conversation_context=SimpleNamespace(temporal_resolution=SimpleNamespace(local_date=date(2026, 5, 14))),
        coach_bundle=SimpleNamespace(week_summary="Semaine compacte", planning_context="Planning compact"),
        state=SimpleNamespace(scheduled_sessions=(), activities=(), active_facts=()),
        pending_confirmation=None,
        turn_context=turn_context,
    )

    assert result is not None
    assert calls
    assert turn_context["canonical_understanding"]["intent"] == "plan_change"
```

- [ ] **Step 2: Run bridge tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_understanding_bridge.py
```

Expected:

```text
ImportError: cannot import name 'conversation_understanding_bridge'
```

- [ ] **Step 3: Implement bridge**

Create `backend/src/fitmas/legacy/conversation_understanding_bridge.py`:

```python
from __future__ import annotations

import logging
import os
from typing import Any

from fitmas.decision import CoachUnderstanding
from fitmas.llm.understanding_service import LLMUnderstandingService, UnderstandingRequest

logger = logging.getLogger(__name__)


def understanding_runtime_shadow_enabled() -> bool:
    return str(os.getenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW") or "").strip() in {"1", "true", "True", "on"}


def understanding_runtime_planning_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER") or "").strip() in {"1", "true", "True", "on"}


def run_canonical_understanding_shadow(
    *,
    service: LLMUnderstandingService | None = None,
    user,
    user_text: str,
    turn_plan,
    conversation_context,
    coach_bundle,
    state,
    pending_confirmation,
    turn_context: dict[str, object],
) -> CoachUnderstanding | None:
    if not understanding_runtime_shadow_enabled():
        return None
    service = service or LLMUnderstandingService()
    request = UnderstandingRequest(
        event_summary=_event_summary(user=user, user_text=user_text, turn_plan=turn_plan, pending_confirmation=pending_confirmation),
        context_blocks=_context_blocks(
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            state=state,
        ),
    )
    try:
        understanding = service.understand(request)
    except Exception:
        logger.exception("decision_runtime.canonical_understanding_failed user=%s", getattr(user, "id", None))
        turn_context["canonical_understanding_error"] = "exception"
        return None
    if understanding is None:
        turn_context["canonical_understanding_error"] = "empty_or_invalid"
        return None
    turn_context["canonical_understanding"] = understanding_to_turn_context_payload(understanding)
    logger.info(
        "decision_runtime.canonical_understanding user=%s intent=%s confidence=%.2f signals=%s requested_change=%s pending=%s",
        getattr(user, "id", None),
        understanding.intent,
        understanding.confidence,
        len(understanding.extracted_signals),
        1 if understanding.requested_change is not None else 0,
        1 if understanding.pending_resolution is not None else 0,
    )
    return understanding


def understanding_to_turn_context_payload(understanding: CoachUnderstanding) -> dict[str, object]:
    requested_change = understanding.requested_change
    return {
        "intent": understanding.intent,
        "confidence": understanding.confidence,
        "user_summary": understanding.user_summary,
        "signals": [
            {
                "type": signal.type,
                "label": signal.label,
                "status": signal.status,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "evidence": signal.evidence,
                "payload": dict(signal.payload),
            }
            for signal in understanding.extracted_signals
        ],
        "requested_change": None
        if requested_change is None
        else {
            "kind": requested_change.kind,
            "source_ref": requested_change.source_ref,
            "target_ref": requested_change.target_ref,
            "desired_sport": requested_change.desired_sport,
            "desired_duration_min": requested_change.desired_duration_min,
            "desired_intensity": requested_change.desired_intensity,
            "reason": requested_change.reason,
            "risk_signals": list(requested_change.risk_signals),
        },
        "pending_resolution": None
        if understanding.pending_resolution is None
        else {
            "type": understanding.pending_resolution.type,
            "reason": understanding.pending_resolution.reason,
            "selected_candidate_id": understanding.pending_resolution.selected_candidate_id,
            "requested_changes": understanding.pending_resolution.requested_changes,
            "question": understanding.pending_resolution.question,
        },
        "clarification_need": None
        if understanding.clarification_need is None
        else {
            "reason": understanding.clarification_need.reason,
            "missing_fields": list(understanding.clarification_need.missing_fields),
            "question_intent": understanding.clarification_need.question_intent,
        },
    }


def _event_summary(*, user, user_text: str, turn_plan, pending_confirmation) -> str:
    return (
        f"source=telegram type=user_message user_id={getattr(user, 'id', None)} "
        f"primary_intent={getattr(turn_plan, 'primary_intent', None)} "
        f"pending_active={pending_confirmation is not None} "
        f"text={user_text}"
    )


def _context_blocks(*, conversation_context, coach_bundle, state) -> tuple[str, ...]:
    local_date = getattr(getattr(conversation_context, "temporal_resolution", None), "local_date", None)
    return (
        f"Local date: {local_date}",
        f"Week summary: {getattr(coach_bundle, 'week_summary', '')}",
        f"Planning context: {getattr(coach_bundle, 'planning_context', '')}",
        f"Scheduled sessions count: {len(tuple(getattr(state, 'scheduled_sessions', ()) or ()))}",
        f"Activities count: {len(tuple(getattr(state, 'activities', ()) or ()))}",
        f"Active facts count: {len(tuple(getattr(state, 'active_facts', ()) or ()))}",
    )
```

- [ ] **Step 4: Wire bridge into `conversation_pipeline.py`**

Modify imports:

```python
from fitmas.legacy import conversation_understanding_bridge
```

In `_run_conversation_turn_impl`, immediately before `dependencies.decide(...)`, initialize:

```python
canonical_understanding = conversation_understanding_bridge.run_canonical_understanding_shadow(
    user=user,
    user_text=payload.text,
    turn_plan=turn_plan,
    conversation_context=conversation_context,
    coach_bundle=coach_bundle,
    state=state,
    pending_confirmation=pending_confirmation,
    turn_context=turn_context,
)
```

Keep the existing `decision = dependencies.decide(...)` call unchanged.

When calling `conversation_planning_bridge.maybe_handle_planning_runtime_cutover(...)`, add:

```python
canonical_understanding=canonical_understanding,
understanding_planning_cutover_enabled=(
    conversation_understanding_bridge.understanding_runtime_planning_cutover_enabled()
),
```

- [ ] **Step 5: Run bridge and core tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_understanding_bridge.py tests/test_conversation_understanding_shadow.py tests/test_core_flows.py
```

Expected:

```text
PASS
```

## Task 4 — Planning Runtime Consumes Canonical Understanding When Enabled

**Files:**

- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `backend/src/fitmas/legacy/conversation_planning_bridge.py`
- Modify: `tests/test_conversation_planning_runtime_adapter.py`
- Modify: `tests/test_phase8b_planning_cutover.py`

- [ ] **Step 1: Write cutover tests**

Append to `tests/test_conversation_planning_runtime_adapter.py`:

```python
def test_planning_runtime_attempt_uses_canonical_understanding_when_supplied(monkeypatch) -> None:
    from fitmas.decision import CoachUnderstanding, RequestedPlanChange
    from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision

    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(kind="block", reason="canonical blocked")

    monkeypatch.setattr(
        "fitmas.legacy.planning_runtime_adapter.decide_plan_change",
        fake_decide_plan_change,
    )

    understanding = CoachUnderstanding(
        intent="plan_change",
        confidence=0.9,
        user_summary="canonical move",
        extracted_signals=(),
        requested_change=RequestedPlanChange(
            kind="move",
            source_ref="seance dure",
            target_ref="vendredi",
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity=None,
            reason="fatigue",
            risk_signals=("fatigue",),
        ),
        pending_resolution=None,
        clarification_need=None,
    )

    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision=object(),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="texte utilisateur",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
        understanding=understanding,
    )

    assert attempt.applicable is True
    assert attempt.result is not None
    assert calls[0].source_ref == "seance dure"
    assert calls[0].target_ref == "vendredi"


def test_planning_runtime_attempt_falls_back_to_legacy_adapter_without_understanding(monkeypatch) -> None:
    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(kind="block", reason="legacy blocked")

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
        understanding=None,
    )

    assert attempt.applicable is True
    assert calls
    assert calls[0].source_ref == "session_id:42"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_planning_runtime_adapter.py::test_planning_runtime_attempt_uses_canonical_understanding_when_supplied
```

Expected:

```text
TypeError: run_planning_runtime_attempt_from_legacy_decision() got an unexpected keyword argument 'understanding'
```

- [ ] **Step 3: Update planning runtime adapter**

In `backend/src/fitmas/legacy/planning_runtime_adapter.py`, update imports:

```python
from fitmas.decision import CoachUnderstanding
```

Change signature:

```python
def run_planning_runtime_attempt_from_legacy_decision(
    *,
    decision,
    context,
    db,
    user,
    source_text: str,
    coach_state_bundle,
    reviewer_request_json_fn,
    understanding: CoachUnderstanding | None = None,
) -> PlanningRuntimeAdapterAttempt:
```

At the start of the function, replace the unconditional adapter call with:

```python
    if understanding is None:
        understanding = coach_decision_to_understanding(decision)
    if understanding.requested_change is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="no_requested_plan_change",
        )
```

Then keep the existing `decide_plan_change(...)` call using:

```python
understanding.requested_change
```

- [ ] **Step 4: Update conversation planning bridge**

In `backend/src/fitmas/legacy/conversation_planning_bridge.py`, add parameters:

```python
canonical_understanding=None,
understanding_planning_cutover_enabled: bool = False,
```

When calling `run_planning_runtime_attempt_from_legacy_decision(...)`, pass:

```python
understanding=canonical_understanding if understanding_planning_cutover_enabled else None,
```

Store source in the turn context when available:

```python
if turn_context is not None and canonical_understanding is not None:
    turn_context["planning_runtime_understanding_source"] = (
        "canonical" if understanding_planning_cutover_enabled else "legacy_adapter"
    )
```

- [ ] **Step 5: Run planning tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_planning_runtime_adapter.py tests/test_phase8b_planning_cutover.py tests/test_conversation_planning_runtime_reply_composer.py
```

Expected:

```text
PASS
```

## Task 5 — Conversation Integration With Flags

**Files:**

- Modify: `tests/test_core_flows.py`
- Modify: `tests/test_conversation_debug_endpoint.py`
- Test: `tests/test_phase8e_understanding_cutover_architecture.py`

- [ ] **Step 1: Add integration tests that flags preserve behavior**

Append to `tests/test_core_flows.py` near other Decision Runtime tests:

```python
def test_canonical_understanding_shadow_flag_off_does_not_call_service(self):
    import fitmas.api_messages as api_messages
    from fitmas.legacy import conversation_understanding_bridge
    from fitmas.llm import CoachDecision

    original_decide = api_messages.decide
    original_extract_facts = api_messages.extract_facts
    original_service = conversation_understanding_bridge.LLMUnderstandingService
    try:
        api_messages.decide = lambda *args, **kwargs: CoachDecision(
            response_type="no_change",
            rationale="lecture",
            fitmas_message="Rien a changer.",
        )
        api_messages.extract_facts = lambda *args, **kwargs: []

        class FailingService:
            def understand(self, request):
                raise AssertionError("canonical understanding should be off")

        conversation_understanding_bridge.LLMUnderstandingService = lambda: FailingService()
        os.environ.pop("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", None)

        response = self.client.post("/api/v0/messages", json={"text": "redonne le plan actuel"})

        assert response.status_code == 200
    finally:
        api_messages.decide = original_decide
        api_messages.extract_facts = original_extract_facts
        conversation_understanding_bridge.LLMUnderstandingService = original_service
        os.environ.pop("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", None)


def test_canonical_understanding_shadow_flag_on_records_context(self):
    import fitmas.api_messages as api_messages
    from fitmas.decision import CoachUnderstanding
    from fitmas.legacy import conversation_understanding_bridge
    from fitmas.llm import CoachDecision

    original_decide = api_messages.decide
    original_extract_facts = api_messages.extract_facts
    original_service = conversation_understanding_bridge.LLMUnderstandingService
    try:
        api_messages.decide = lambda *args, **kwargs: CoachDecision(
            response_type="no_change",
            rationale="lecture",
            fitmas_message="Rien a changer.",
        )
        api_messages.extract_facts = lambda *args, **kwargs: []

        class FakeService:
            def understand(self, request):
                return CoachUnderstanding(
                    intent="plan_lookup",
                    confidence=0.88,
                    user_summary="lookup",
                    extracted_signals=(),
                    requested_change=None,
                    pending_resolution=None,
                    clarification_need=None,
                )

        conversation_understanding_bridge.LLMUnderstandingService = lambda: FakeService()
        os.environ["FITMAS_UNDERSTANDING_RUNTIME_SHADOW"] = "1"

        response = self.client.post(
            "/api/v0/messages",
            json={"text": "redonne le plan actuel", "client_message_key": "understanding-shadow-on"},
        )

        assert response.status_code == 200
        row = repo.get_conversation_turn_by_client_message_key(
            self.db,
            self.user.id,
            "understanding-shadow-on",
        )
        assert row is not None
        context = json.loads(row.context_json or "{}")
        assert context["canonical_understanding"]["intent"] == "plan_lookup"
    finally:
        api_messages.decide = original_decide
        api_messages.extract_facts = original_extract_facts
        conversation_understanding_bridge.LLMUnderstandingService = original_service
        os.environ.pop("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", None)
```

If `tests/test_core_flows.py` already imports `json`, `os` and `repo`, reuse existing imports. If one is missing, add it at the top.

- [ ] **Step 2: Run the two tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py::FitMASCoreFlowsTest::test_canonical_understanding_shadow_flag_on_records_context
```

Expected before wiring:

```text
KeyError: 'canonical_understanding'
```

- [ ] **Step 3: Wire imports and variables in conversation pipeline**

In `backend/src/fitmas/conversation_pipeline.py`, add:

```python
from fitmas.legacy import conversation_understanding_bridge
```

Before `decision = dependencies.decide(...)`, add the canonical shadow call from Task 3.

Make sure `canonical_understanding` exists even when the flag is off:

```python
canonical_understanding = conversation_understanding_bridge.run_canonical_understanding_shadow(...)
```

When calling `conversation_planning_bridge.maybe_handle_planning_runtime_cutover(...)`, pass the two new args.

- [ ] **Step 4: Run integration tests**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_conversation_debug_endpoint.py tests/test_phase8e_understanding_cutover_architecture.py
```

Expected:

```text
PASS
```

## Task 6 — Prompt And Snapshot Guarding

**Files:**

- Modify: `tests/test_llm_prompts_understanding.py`
- Modify: `tests/test_phase6_prompt_architecture.py`
- Modify if needed: `backend/src/fitmas/llm/prompts/understanding.py`

- [ ] **Step 1: Add prompt guard tests**

Append to `tests/test_llm_prompts_understanding.py`:

```python
def test_understanding_prompt_forbids_visible_speech_and_writes() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="source=telegram type=user_message text=deplace demain",
            context_blocks=("Plan compact",),
        )
    )
    text = f"{rendered.system}\n{rendered.prompt}"

    assert "Tu ne parles pas au user" in text
    assert "Tu ne composes aucun message visible" in text
    assert "Tu ne produis pas de patch planning" in text
    assert "PlanPatch" not in text
    assert "fitmas_message" not in text
```

- [ ] **Step 2: Run prompt tests**

Run:

```bash
./scripts/test-backend -q tests/test_llm_prompts_understanding.py tests/test_phase6_prompt_architecture.py
```

Expected:

```text
PASS
```

## Task 7 — Docs And Verification

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update refactor canon**

Add `Livres en Phase 8E` to `docs/DECISION-RUNTIME-REFACTOR.md`:

```text
Livres en Phase 8E :

- `LLMUnderstandingService` existe sous `fitmas.llm.understanding_service`.
- le parser refuse reply_text, fitmas_message, PlanPatch, MutationDecision et commands.
- `conversation_understanding_bridge.py` appelle Understanding en shadow opt-in.
- `FITMAS_UNDERSTANDING_RUNTIME_SHADOW` est off par defaut.
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` est off par defaut.
- planning runtime peut consommer un `CoachUnderstanding` canonique quand le flag cutover est actif.
- `CoachDecision` reste fallback actions/reply jusqu'a la phase suivante.
```

- [ ] **Step 2: Update legacy kill list**

Add under Phase 8:

```text
Phase 8E rapproche le cutover Understanding mais ne supprime pas `llm/decision_legacy.py`.
Le legacy provider reste utilise pour `CoachDecision` tant que memory/execution/pending ne sont pas commandes runtime.
```

- [ ] **Step 3: Update build order**

Add Phase 8E status and exact verification evidence after running tests.

- [ ] **Step 4: Run architecture gates**

Run:

```bash
./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py
```

Expected:

```text
PASS
```

- [ ] **Step 5: Run targeted behavior gates**

Run:

```bash
./scripts/test-backend -q tests/test_llm_understanding_service.py tests/test_conversation_understanding_bridge.py tests/test_conversation_planning_runtime_adapter.py tests/test_core_flows.py
```

Expected:

```text
PASS
```

- [ ] **Step 6: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
1130+ passed, 11 skipped, 11 subtests passed
```

- [ ] **Step 7: Run cutover smoke with existing flags**

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
RESULT: OK
```

- [ ] **Step 8: Run one opt-in Understanding shadow smoke**

Run:

```bash
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion
```

Expected:

```text
exit 0
no visible reply regression
conversation turn context includes canonical_understanding
```

If the smoke script does not print context, verify via DB/log output or add a tiny assertion to the smoke harness in a separate test-only step.

## Acceptance Criteria

8E is complete only if all are true:

```text
1. `fitmas.llm.understanding_service.LLMUnderstandingService` exists.
2. It returns `CoachUnderstanding | None`, never `CoachDecision`.
3. The parser rejects visible replies, PlanPatch, MutationDecision and commands.
4. Understanding shadow is opt-in and behavior-preserving when off.
5. conversation_pipeline.py does not import the LLM service directly.
6. planning runtime can consume canonical `CoachUnderstanding.requested_change` when explicitly enabled.
7. decision/ remains pure: no llm, legacy, DB, tools or conversation imports.
8. No deterministic parsing over free user text was added.
9. Full backend passes.
10. Existing cutover smoke passes.
11. One opt-in Understanding shadow smoke passes.
```

## What 8E Explicitly Does Not Do

```text
- It does not delete `llm/decision_legacy.py`.
- It does not delete `conversation_prompt_modules.py`.
- It does not remove `CoachDecision` from `ConversationPipelineDependencies`.
- It does not move memory_actions or execution_actions into CommandBus.
- It does not produce a user-visible reply from Understanding.
- It does not commit planning from Understanding directly.
- It does not enable Understanding shadow by default.
```

## Suggested Execution Order

```text
8E1 architecture gates
8E2 parser + Understanding service
8E3 conversation Understanding bridge
8E4 planning runtime consumes canonical understanding behind flag
8E5 conversation integration with flags
8E6 prompt guards
8E7 docs + verification
```

## Expected Next Phase

If 8E lands cleanly, next phase should be 8F:

```text
Command extraction slice:
- map canonical Understanding signals to MemoryCommand / ExecutionCommand drafts;
- move memory/execution writes behind CommandBus;
- keep ReplyComposer as only visible speech path;
- shrink CoachDecision to provider compat only.
```
