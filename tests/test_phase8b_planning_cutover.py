from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy import conversation_planning_bridge
from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_understanding


ROOT = Path(__file__).resolve().parents[1]


def _requested_change() -> RequestedPlanChange:
    return RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="move",
        risk_signals=(),
    )


def _understanding() -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="plan_change",
        confidence=0.9,
        user_summary="move",
        extracted_signals=(),
        requested_change=_requested_change(),
        pending_resolution=None,
        clarification_need=None,
    )


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


def test_planning_runtime_attempt_marks_requested_change_as_applicable(monkeypatch) -> None:
    def fake_decide_plan_change(requested_change, **kwargs):
        return SimpleNamespace(kind="block", reason="blocked")

    monkeypatch.setattr(
        "fitmas.legacy.planning_runtime_adapter.decide_plan_change",
        fake_decide_plan_change,
    )

    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=_understanding(),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert attempt.applicable is True
    assert attempt.result is not None


def test_runtime_mapper_blocks_applicable_unhandled_change() -> None:
    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "plan_blocked"
            return SimpleNamespace(text="Je bloque ce changement.", verified=True)

    outcome = conversation_planning_bridge.canonical_planning_blocked_outcome(
        reason="adapter_failed",
        user_text="deplace",
        grounding_facts=(),
        decision_reply_composer_fn=lambda: FakeComposer(),
    )

    assert outcome.response_mode == "canonical_planning_blocked"
    assert outcome.mutation_applied is False
    assert outcome.pending_confirmation is False


def test_old_coachdecision_planning_cutover_route_is_removed() -> None:
    pipeline = (ROOT / "backend/src/fitmas/conversation_pipeline.py").read_text()
    bridge = (ROOT / "backend/src/fitmas/legacy/conversation_planning_bridge.py").read_text()

    assert "maybe_handle_planning_runtime_cutover" not in pipeline
    assert "maybe_handle_planning_runtime_cutover" not in bridge
    assert "FITMAS_PLANNING_RUNTIME_CUTOVER" not in bridge
