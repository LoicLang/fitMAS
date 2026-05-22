from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange
from fitmas.decision.planning_runtime import run_planning_runtime_attempt_from_understanding
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult


def _understanding(requested_change: RequestedPlanChange | None = None) -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="plan_change",
        confidence=0.9,
        user_summary="canonical move",
        extracted_signals=(),
        requested_change=requested_change,
        pending_resolution=None,
        clarification_need=None,
    )


def _requested_change() -> RequestedPlanChange:
    return RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )


def test_adapter_marks_missing_understanding_as_not_applicable() -> None:
    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=None,
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="ok",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert attempt.applicable is False
    assert attempt.result is None
    assert attempt.reason == "missing_understanding"


def test_adapter_marks_understanding_without_requested_change_as_not_applicable() -> None:
    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=_understanding(requested_change=None),
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


def test_adapter_runs_decision_service_for_requested_change(monkeypatch) -> None:
    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(kind="block", reason="Aucune option valide.")

    monkeypatch.setattr("fitmas.decision.planning_runtime.decide_plan_change", fake_decide_plan_change)

    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=_understanding(_requested_change()),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert attempt.applicable is True
    assert attempt.result is not None
    assert attempt.reason == "non_standard_planning_result"


def test_adapter_applies_command_service_for_planning_decision(monkeypatch) -> None:
    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason="blocked",
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )

    class FakeCommandService:
        def __init__(self, *, db, user):
            pass

        def apply(self, decision, **kwargs):
            calls.append((decision, kwargs))
            return PlanningCommandResult(
                status="blocked",
                event_count=0,
                pending_confirmation_id=None,
                service_result=None,
                payload={"reason": "blocked"},
            )

    monkeypatch.setattr("fitmas.decision.planning_runtime.decide_plan_change", fake_decide_plan_change)
    monkeypatch.setattr("fitmas.decision.planning_runtime.PlanningCommandService", FakeCommandService)

    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=_understanding(_requested_change()),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert attempt.result is not None
    assert attempt.result.command_result is not None
    assert attempt.result.command_result.status == "blocked"
