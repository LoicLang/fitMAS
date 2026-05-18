from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal
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


def test_run_canonical_understanding_shadow_skips_when_provider_opted_out(monkeypatch) -> None:
    calls: list[str] = []

    class FakeService:
        def understand(self, request):
            calls.append(request.event_summary)
            return _understanding()

    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "0")

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


def test_default_non_planning_cutover_runs_for_active_pending(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_PENDING_FROM_UNDERSTANDING", raising=False)

    assert bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="close_turn", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_default_non_planning_cutover_runs_for_execution_turn(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_COMMANDS_FROM_UNDERSTANDING", raising=False)

    assert bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(
            primary_intent="execution_report",
            secondary_intents=(),
            has_plan_mutation=False,
            mutation_signal=False,
        ),
        pending_confirmation=None,
    )


def test_default_non_planning_cutover_runs_for_availability_intent(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_COMMANDS_FROM_UNDERSTANDING", raising=False)

    assert bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(
            primary_intent="availability_constraint",
            secondary_intents=(),
            has_plan_mutation=False,
            mutation_signal=False,
        ),
        pending_confirmation=None,
    )


def test_default_non_planning_cutover_skips_read_only_lookup(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)

    assert not bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_runs_understanding_for_plan_mutation(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=(), has_plan_mutation=True),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_opt_out_skips_understanding_for_plan_mutation(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "0")

    assert not bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=(), has_plan_mutation=True),
        pending_confirmation=None,
    )


def test_non_planning_cutover_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", "0")
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)

    assert not bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="execution_report", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_explicit_shadow_runs_even_when_non_planning_cutover_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", "0")
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", "1")

    assert bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=None,
    )


def test_provider_pivot_defaults_on_for_canonical_command(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PROVIDER_NON_PLANNING", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_COMMANDS_FROM_UNDERSTANDING", raising=False)

    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Piscine indisponible.",
        extracted_signals=(
            UserSignal(
                type="availability",
                label="piscine fermee",
                status="unavailable",
                severity="unknown",
                confidence=0.9,
                evidence="piscine fermee",
                payload={
                    "action_type": "record_availability",
                    "window_text": "piscine fermee",
                    "availability": "unavailable",
                    "sport_type": "swimming",
                },
            ),
        ),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    assert bridge.should_use_canonical_understanding_without_legacy(
        understanding=understanding,
        turn_plan=SimpleNamespace(primary_intent="availability_constraint", secondary_intents=()),
        pending_confirmation=None,
    )


def test_provider_pivot_defaults_on_for_canonical_pending(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PROVIDER_NON_PLANNING", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_PENDING_FROM_UNDERSTANDING", raising=False)

    understanding = CoachUnderstanding(
        intent="pending_response",
        confidence=0.9,
        user_summary="Confirmation explicite.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=PendingResolution(
            type="accept_pending",
            reason="ok explicite",
            selected_candidate_id=None,
            requested_changes=None,
            question=None,
        ),
        clarification_need=None,
    )

    assert bridge.should_use_canonical_understanding_without_legacy(
        understanding=understanding,
        turn_plan=SimpleNamespace(primary_intent="close_turn", secondary_intents=()),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_provider_pivot_keeps_legacy_for_planning(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PROVIDER_NON_PLANNING", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)

    assert not bridge.should_use_canonical_understanding_without_legacy(
        understanding=_understanding(),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=()),
        pending_confirmation=None,
    )


def test_artifact_from_understanding_is_user_safe_and_non_mutating() -> None:
    understanding = CoachUnderstanding(
        intent="execution_report",
        confidence=0.9,
        user_summary="Seance faite.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    artifact = bridge.coach_decision_artifact_from_understanding(
        understanding,
        turn_plan=SimpleNamespace(primary_intent="execution_report"),
    )

    assert artifact.kind == "coach_decision"
    assert artifact.source == "coach_understanding"
    assert artifact.response_type == "reply"
    assert artifact.plan_patch is None
    assert artifact.mutation_decision is None
    assert artifact.memory_actions == ()
    assert artifact.execution_actions == ()
    assert "fitmas_message" not in repr(artifact.payload)
    assert "plan_patch" not in repr(artifact.payload)
