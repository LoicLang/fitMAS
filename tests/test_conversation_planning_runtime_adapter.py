from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.legacy.planning_runtime_adapter import maybe_run_planning_runtime_from_legacy_decision
from fitmas.llm import CoachDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def test_adapter_returns_none_for_non_planning_decision() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture",
        fitmas_message="Message legacy.",
    )

    result = maybe_run_planning_runtime_from_legacy_decision(
        decision_artifact=legacy_decision_artifact_from_raw(decision),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="ok",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result is None


def test_adapter_runs_decision_service_for_requested_change(monkeypatch) -> None:
    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(
            kind="block",
            reason="Aucune option valide.",
            command_result=None,
            pending_confirmation_id=None,
        )

    monkeypatch.setattr("fitmas.legacy.planning_runtime_adapter.decide_plan_change", fake_decide_plan_change)

    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement",
        fitmas_message="Message legacy.",
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

    result = maybe_run_planning_runtime_from_legacy_decision(
        decision_artifact=legacy_decision_artifact_from_raw(decision),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert result is not None
    assert result.kind == "block"


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

    monkeypatch.setattr("fitmas.legacy.planning_runtime_adapter.decide_plan_change", fake_decide_plan_change)
    monkeypatch.setattr("fitmas.legacy.planning_runtime_adapter.PlanningCommandService", FakeCommandService)

    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement",
        fitmas_message="Message legacy.",
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

    result = maybe_run_planning_runtime_from_legacy_decision(
        decision_artifact=legacy_decision_artifact_from_raw(decision),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert result is not None
    assert result.command_result is not None
    assert result.command_result.status == "blocked"


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
        decision_artifact=legacy_decision_artifact_from_raw(None),
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
    from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision

    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(kind="block", reason="legacy blocked")

    monkeypatch.setattr(
        "fitmas.legacy.planning_runtime_adapter.decide_plan_change",
        fake_decide_plan_change,
    )

    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement",
        fitmas_message="Message legacy.",
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

    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision_artifact=legacy_decision_artifact_from_raw(decision),
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


def test_planning_bridge_does_not_pass_non_planning_canonical_understanding(monkeypatch) -> None:
    from fitmas.decision import CoachUnderstanding, RequestedPlanChange
    from fitmas.legacy import conversation_planning_bridge

    calls = []

    def fake_run_planning_runtime_attempt_from_legacy_decision(**kwargs):
        calls.append(kwargs.get("understanding"))
        return SimpleNamespace(applicable=False, result=None, reason="no_requested_plan_change")

    monkeypatch.setattr(
        "fitmas.legacy.conversation_planning_bridge.run_planning_runtime_attempt_from_legacy_decision",
        fake_run_planning_runtime_attempt_from_legacy_decision,
    )

    canonical_understanding = CoachUnderstanding(
        intent="execution_report",
        confidence=0.9,
        user_summary="missed",
        extracted_signals=(),
        requested_change=RequestedPlanChange(
            kind="move",
            source_ref="hier",
            target_ref="aujourd'hui",
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity=None,
            reason="bruit",
            risk_signals=(),
        ),
        pending_resolution=None,
        clarification_need=None,
    )
    turn_context: dict[str, object] = {}

    outcome = conversation_planning_bridge.maybe_handle_planning_runtime_cutover(
        decision_artifact=legacy_decision_artifact_from_raw(None),
        canonical_understanding=canonical_understanding,
        understanding_planning_cutover_enabled=True,
        state=SimpleNamespace(),
        conversation_context=SimpleNamespace(),
        coach_bundle=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="j'ai rate hier",
        reviewer_request_json_fn=None,
        grounding_facts=(),
        planning_context_from_turn_state_fn=lambda **_kwargs: SimpleNamespace(),
        decision_reply_composer_fn=lambda: None,
        compose_no_change_reply_for_turn_fn=lambda **_kwargs: ("", None),
        turn_context=turn_context,
        action_result={},
    )

    assert outcome is None
    assert calls == [None]
    assert turn_context["planning_runtime_understanding_source"] == "legacy_adapter"
