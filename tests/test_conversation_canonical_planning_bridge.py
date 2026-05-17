from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.legacy import conversation_canonical_planning_bridge as bridge
from fitmas.legacy.planning_runtime_adapter import PlanningRuntimeAdapterAttempt


def _requested_change(
    kind: str = "move",
    *,
    source_ref: str | None = "session_id:42",
    target_ref: str | None = "date:2026-05-22",
    desired_sport: str | None = None,
) -> RequestedPlanChange:
    return RequestedPlanChange(
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        desired_sport=desired_sport,
        desired_duration_min=None,
        desired_intensity=None,
        reason="demande user",
        risk_signals=(),
    )


def _understanding(
    *,
    requested_change: RequestedPlanChange | None = None,
    intent: str = "plan_change",
    pending_resolution=None,
    signals=(),
) -> CoachUnderstanding:
    return CoachUnderstanding(
        intent=intent,
        confidence=0.91,
        user_summary="Demande de changement planning.",
        extracted_signals=tuple(signals),
        requested_change=requested_change if requested_change is not None else _requested_change(),
        pending_resolution=pending_resolution,
        clarification_need=None,
    )


def _turn_plan(primary_intent: str = "plan_mutation"):
    return SimpleNamespace(primary_intent=primary_intent, secondary_intents=())


def test_canonical_planning_provider_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.canonical_planning_provider_enabled() is False


def test_canonical_planning_provider_accepts_typed_move_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_rejects_free_text_refs(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")

    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(source_ref="seance dure", target_ref="vendredi")
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_rejects_active_pending(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")

    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(),
        turn_plan=_turn_plan(),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_canonical_planning_provider_rejects_pending_resolution(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")

    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            pending_resolution=PendingResolution(
                type="accept_pending",
                reason="ok",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            )
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_rejects_command_signals(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
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

    assert not bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(signals=(signal,)),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_allows_session_preference_metadata_signal(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    signal = UserSignal(
        type="preference",
        label="move_session",
        status="new",
        severity="medium",
        confidence=0.95,
        evidence="deplace la recuperation id 3",
        payload={
            "action_type": "record_preference",
            "preference": "move recovery mobility session to next Monday",
            "polarity": "prefer",
            "scope": "session",
            "target_ref": "session_id:3",
        },
    )

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(source_ref="session_id:3", target_ref="date:2026-05-18"),
            signals=(signal,),
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_calls_runtime_from_understanding_without_legacy(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    calls: list[dict] = []
    planning_result = PlanningDecisionResult(
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

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return PlanningRuntimeAdapterAttempt(applicable=True, result=planning_result, reason="handled")

    def fake_conversation_outcome(result, **kwargs):
        assert result is planning_result
        assert kwargs["original_reply"] == ""
        return SimpleNamespace(
            reply_text="Bloque.",
            response_mode="planning_runtime_block",
            mutation_applied=False,
            pending_confirmation=False,
        )

    monkeypatch.setattr(bridge, "run_planning_runtime_attempt_from_understanding", fake_attempt)
    monkeypatch.setattr(bridge, "conversation_outcome_from_planning_runtime_result", fake_conversation_outcome)
    turn_context: dict[str, object] = {}

    outcome = bridge.handle_canonical_planning(
        understanding=_understanding(),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
        grounding_facts=("truth",),
        decision_reply_composer_fn=lambda: None,
        turn_context=turn_context,
    )

    assert outcome is not None
    assert calls
    assert calls[0]["understanding"].requested_change.source_ref == "session_id:42"
    assert turn_context["legacy_decide"]["legacy_skipped"] is True
    assert turn_context["canonical_planning_provider"]["result"] == "handled"


def test_applicable_canonical_planning_failure_blocks_without_legacy_fallthrough(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")

    def fake_attempt(**kwargs):
        return PlanningRuntimeAdapterAttempt(applicable=True, result=None, reason="runtime_failed")

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "plan_blocked"
            assert "plan_committed" in outcome.reply_contract.forbidden_claims
            return SimpleNamespace(text="Je bloque.", verified=True)

    monkeypatch.setattr(bridge, "run_planning_runtime_attempt_from_understanding", fake_attempt)
    turn_context: dict[str, object] = {}

    outcome = bridge.handle_canonical_planning(
        understanding=_understanding(),
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
        grounding_facts=(),
        decision_reply_composer_fn=lambda: FakeComposer(),
        turn_context=turn_context,
    )

    assert outcome is not None
    assert outcome.response_mode == "planning_runtime_unhandled"
    assert outcome.mutation_applied is False
    assert turn_context["legacy_decide"]["legacy_skipped"] is True
    assert turn_context["canonical_planning_provider"]["result"] == "blocked"
