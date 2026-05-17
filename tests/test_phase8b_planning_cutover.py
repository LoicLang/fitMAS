from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fitmas import conversation_pipeline
from fitmas.decision.reply_request import ReplyResult
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy import conversation_planning_bridge
from fitmas.legacy import conversation_readonly_reply_bridge
from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
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


def _conversation_context() -> SimpleNamespace:
    return SimpleNamespace(temporal_resolution=SimpleNamespace(local_date=date(2026, 5, 14)))


def _turn_state() -> SimpleNamespace:
    return SimpleNamespace(scheduled_sessions=(), activities=(), active_facts=())


def _coach_bundle() -> SimpleNamespace:
    return SimpleNamespace(coach_reading="")


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


def test_planning_runtime_attempt_marks_non_planning_as_not_applicable() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture",
        fitmas_message="Rien a changer.",
    )

    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision_artifact=legacy_decision_artifact_from_raw(decision),
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
        decision_artifact=legacy_decision_artifact_from_raw(_plan_patch_decision()),
        context=SimpleNamespace(execution=SimpleNamespace(activities=()), memory=SimpleNamespace(active_facts=())),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert attempt.applicable is True
    assert attempt.result is not None


def test_cutover_helper_uses_runtime_attempt_when_flag_on(monkeypatch) -> None:
    calls = []

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            return ReplyResult(text="Runtime block.", verified=True, fallback_used=False, reason=None)

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(applicable=True, result=_planning_result(), reason="handled")

    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")
    monkeypatch.setattr(conversation_planning_bridge, "run_planning_runtime_attempt_from_legacy_decision", fake_attempt)

    outcome = conversation_planning_bridge.maybe_handle_planning_runtime_cutover(
        decision_artifact=legacy_decision_artifact_from_raw(_plan_patch_decision()),
        state=_turn_state(),
        conversation_context=_conversation_context(),
        coach_bundle=_coach_bundle(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        source_text="deplace",
        reviewer_request_json_fn=None,
        grounding_facts=(),
        planning_context_from_turn_state_fn=conversation_pipeline._planning_context_from_turn_state,
        decision_reply_composer_fn=lambda: FakeComposer(),
        compose_no_change_reply_for_turn_fn=conversation_readonly_reply_bridge.compose_no_change_reply_for_turn,
    )

    assert calls
    assert outcome is not None
    assert outcome.response_mode == "planning_runtime_block"
    assert outcome.reply_text == "Runtime block."


def test_cutover_helper_blocks_applicable_unhandled_change(monkeypatch) -> None:
    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            return ReplyResult(
                text="Je bloque ce changement cote runtime.",
                verified=True,
                fallback_used=False,
                reason=None,
            )

    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")
    monkeypatch.setattr(
        conversation_planning_bridge,
        "run_planning_runtime_attempt_from_legacy_decision",
        lambda **kwargs: SimpleNamespace(applicable=True, result=None, reason="adapter_failed"),
    )

    outcome = conversation_planning_bridge.maybe_handle_planning_runtime_cutover(
        decision_artifact=legacy_decision_artifact_from_raw(_plan_patch_decision()),
        state=_turn_state(),
        conversation_context=_conversation_context(),
        coach_bundle=_coach_bundle(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        source_text="deplace",
        reviewer_request_json_fn=None,
        grounding_facts=(),
        planning_context_from_turn_state_fn=conversation_pipeline._planning_context_from_turn_state,
        decision_reply_composer_fn=lambda: FakeComposer(),
        compose_no_change_reply_for_turn_fn=conversation_readonly_reply_bridge.compose_no_change_reply_for_turn,
    )

    assert outcome is not None
    assert outcome.response_mode == "planning_runtime_unhandled"
    assert outcome.mutation_applied is False
    assert outcome.pending_confirmation is False


def test_runtime_cutover_replaces_mixed_legacy_adaptation_branch() -> None:
    source = Path(conversation_pipeline.__file__).read_text(encoding="utf-8")
    runtime_index = source.index("conversation_planning_bridge.maybe_handle_planning_runtime_cutover(")

    assert runtime_index > 0
    assert "_should_try_mixed_plan_adaptation_after_decide" not in source
    assert "_should_try_legacy_plan_adaptation_after_decide" not in source
