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


def test_canonical_planning_provider_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.canonical_planning_provider_enabled() is True


def test_canonical_planning_provider_can_be_disabled_with_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "0")

    assert bridge.canonical_planning_provider_enabled() is False


def test_canonical_planning_provider_accepts_typed_move_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_iso_date_target_ref(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(requested_change=_requested_change(target_ref="2026-05-22")),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_underscore_ref_aliases(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(source_ref="session_3", target_ref="date_2026-05-22")
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_session_id_underscore_alias(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(source_ref="session_id_3", target_ref="date:2026-05-25")
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_session_id_equals_alias(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(source_ref="session_id=3", target_ref="date:2026-05-25")
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_date_based_swap_refs(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(
                kind="swap",
                source_ref="date:2026-05-20",
                target_ref="date:2026-05-21",
            )
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_date_based_source_refs(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    for kind in ("move", "lighten", "replace"):
        assert bridge.should_use_canonical_planning_without_legacy(
            understanding=_understanding(
                requested_change=_requested_change(
                    kind=kind,
                    source_ref="date:2026-05-20",
                    target_ref="date:2026-05-22" if kind == "move" else None,
                    desired_sport="cycling" if kind == "replace" else None,
                )
            ),
            turn_plan=_turn_plan(),
            pending_confirmation=None,
        )


def test_canonical_planning_provider_accepts_create_with_typed_date_and_sport(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(
                kind="create",
                source_ref=None,
                target_ref="date:2026-05-20",
                desired_sport="running",
            )
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_accepts_hard_create_without_sport_for_policy_block(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=RequestedPlanChange(
                kind="create",
                source_ref=None,
                target_ref="date:2026-05-20",
                desired_sport=None,
                desired_duration_min=None,
                desired_intensity="hard",
                reason="ajouter une seance dure",
                risk_signals=("load",),
            )
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_turn_plan_create_can_supply_target_ref_and_keep_hard_intensity(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    unsupported = _understanding(
        requested_change=RequestedPlanChange(
            kind="create",
            source_ref=None,
            target_ref="mercredi",
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity="hard",
            reason="ajouter une seance dure",
            risk_signals=("load",),
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="create_session",
        user_goal="ajouter une seance dure mercredi",
        confidence=0.95,
        temporal_references=(
            {"kind": "weekday", "value": "wednesday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "create"
    assert planned.requested_change.source_ref is None
    assert planned.requested_change.target_ref == "day:wednesday"
    assert planned.requested_change.desired_sport is None
    assert planned.requested_change.desired_intensity == "hard"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_create_can_supply_target_ref_when_understanding_clarifies(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    clarification = CoachUnderstanding(
        intent="clarification",
        confidence=0.7,
        user_summary="Sport manquant pour une creation de seance.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="create_session",
        user_goal="ajouter une seance mercredi",
        confidence=0.95,
        temporal_references=(
            {"kind": "weekday", "value": "wednesday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=clarification, turn_plan=turn_plan)

    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "create"
    assert planned.requested_change.source_ref is None
    assert planned.requested_change.target_ref == "day:wednesday"
    assert planned.requested_change.desired_sport is None
    assert planned.requested_change.desired_intensity is None
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_swap_can_supply_planning_understanding_when_understanding_misclassifies(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    general = _understanding(intent="general_answer", requested_change=None)
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        has_plan_mutation=True,
        mutation_signal=True,
        planning_action="swap_sessions",
        user_goal="echanger mercredi et jeudi",
        confidence=0.95,
        temporal_references=(
            {"kind": "weekday", "value": "wednesday", "role": "target"},
            {"kind": "weekday", "value": "thursday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=general, turn_plan=turn_plan)

    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "swap"
    assert planned.requested_change.source_ref == "day:wednesday"
    assert planned.requested_change.target_ref == "day:thursday"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_swap_replaces_unsupported_planning_understanding(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    availability_signal = UserSignal(
        type="availability",
        label="swap days availability",
        status="new",
        severity="low",
        confidence=0.9,
        evidence="Echange mercredi et jeudi",
        payload={
            "action_type": "record_availability",
            "availability": "available",
            "window_text": "mercredi et jeudi",
            "scope": "day",
        },
    )
    preference_signal = UserSignal(
        type="preference",
        label="sport optimization",
        status="new",
        severity="low",
        confidence=0.8,
        evidence="si c'est mieux sportivement",
        payload={
            "action_type": "record_preference",
            "preference": "sportivement mieux",
            "polarity": "prefer",
            "scope": "general",
        },
    )
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="swap",
            source_ref=None,
            target_ref="mercredi et jeudi",
        ),
        signals=(availability_signal, preference_signal),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="swap_sessions",
        user_goal="swapper les seances du mercredi et du jeudi",
        confidence=0.95,
        temporal_references=(
            {"kind": "weekday", "value": "wednesday", "role": "target"},
            {"kind": "weekday", "value": "thursday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.source_ref == "day:wednesday"
    assert planned.requested_change.target_ref == "day:thursday"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_swap_understanding_normalizes_typed_session_id_phrases_without_turn_plan_refs(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="swap",
            source_ref="session id 1 (Fractionné seuil)",
            target_ref="session id 1 and session id 3",
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="swap_sessions",
        user_goal="echanger le fractionne seuil id 1 avec la recuperation mobilite id 3",
        confidence=0.95,
        temporal_references=(),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "swap"
    assert planned.requested_change.source_ref == "session_id:1"
    assert planned.requested_change.target_ref == "session_id:3"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_move_can_supply_planning_understanding_when_understanding_has_free_refs(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="move",
            source_ref="seance 2 jeudi",
            target_ref="mercredi",
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="move_session",
        user_goal="deplacer la seance du jeudi au mercredi",
        confidence=1.0,
        temporal_references=(
            {"kind": "weekday", "value": "thursday", "role": "source"},
            {"kind": "weekday", "value": "wednesday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "move"
    assert planned.requested_change.source_ref == "day:thursday"
    assert planned.requested_change.target_ref == "day:wednesday"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_move_can_reuse_machine_source_from_understanding(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="move",
            source_ref="session_id:3",
            target_ref="lundi prochain",
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="move_session",
        user_goal="deplacer la seance id 3 a lundi prochain",
        confidence=0.95,
        temporal_references=(
            {"kind": "relative_day", "value": "monday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "move"
    assert planned.requested_change.source_ref == "session_id:3"
    assert planned.requested_change.target_ref == "day:monday"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_replace_can_supply_source_ref_and_keep_desired_sport(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="replace",
            source_ref="Natation dimanche",
            target_ref="Velo facile",
            desired_sport="cycling",
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="replace_session",
        user_goal="remplacer la natation du dimanche par un velo facile",
        confidence=0.95,
        temporal_references=(
            {"kind": "weekday", "value": "sunday", "role": "target"},
        ),
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "replace"
    assert planned.requested_change.source_ref == "day:sunday"
    assert planned.requested_change.target_ref is None
    assert planned.requested_change.desired_sport == "cycling"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_sport_unavailable_can_supply_sport_window_replace(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    availability_signal = UserSignal(
        type="availability",
        label="unable_to_swim_2_weeks",
        status="new",
        severity="medium",
        confidence=1.0,
        evidence="Je ne peux pas nager pendant deux semaines",
        payload={
            "action_type": "record_availability",
            "availability": "unavailable",
            "scope": "sport",
            "sport_type": "swimming",
            "starts_on": "2026-05-18",
            "ends_on": "2026-06-01",
        },
    )
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="remove_optional",
            source_ref=None,
            target_ref="date:2026-05-18",
        ),
        signals=(availability_signal,),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=("availability_constraint",),
        planning_action="update_session",
        user_goal="adapter le plan car la natation est indisponible deux semaines",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "sport",
            "sport_type": "swimming",
            "starts_on": "2026-05-18",
            "ends_on": "2026-06-01",
        },
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "replace"
    assert planned.requested_change.source_ref == "sport_window:swimming:2026-05-18:2026-06-01"
    assert planned.requested_change.target_ref is None
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_general_unavailability_can_supply_constraint_window(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    availability_signal = UserSignal(
        type="availability",
        label="travel_window",
        status="new",
        severity="medium",
        confidence=1.0,
        evidence="Je voyage de mercredi a vendredi",
        payload={
            "action_type": "record_availability",
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )
    unsupported = _understanding(
        requested_change=_requested_change(
            kind="unknown",
            source_ref=None,
            target_ref=None,
        ),
        signals=(availability_signal,),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=("availability_constraint",),
        planning_action="update_session",
        user_goal="adapter le plan car je voyage de mercredi a vendredi",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    planned = bridge.planning_understanding_for_provider(understanding=unsupported, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "constraint_window"
    assert planned.requested_change.source_ref == "availability_window:unavailable:general:2026-05-20:2026-05-22"
    assert planned.requested_change.target_ref is None
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_availability_primary_without_planning_request_stays_memory_only(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage de mercredi a vendredi.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=(),
        mutation_signal=False,
        planning_action=None,
        user_goal="voyage de mercredi a vendredi",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    assert not bridge.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=None,
    )
    assert bridge.planning_understanding_for_provider(
        understanding=understanding,
        turn_plan=turn_plan,
    ) is understanding


def test_availability_primary_with_typed_planning_request_can_use_canonical_planning(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage de mercredi a vendredi, adaptation demandee.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=("plan_mutation",),
        mutation_signal=True,
        planning_action="update_session",
        user_goal="voyage de mercredi a vendredi, adapte si besoin",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    planned = bridge.planning_understanding_for_provider(understanding=understanding, turn_plan=turn_plan)

    assert bridge.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=None,
    )
    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "constraint_window"
    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=planned,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )


def test_turn_plan_general_unavailability_emits_availability_window_with_status(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage avec adaptation demandee.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=("plan_mutation",),
        mutation_signal=True,
        planning_action="update_session",
        user_goal="voyage de mercredi a vendredi, adapte si besoin",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    planned = bridge.planning_understanding_for_provider(understanding=understanding, turn_plan=turn_plan)

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.source_ref == "availability_window:unavailable:general:2026-05-20:2026-05-22"


def test_canonical_planning_prepared_trace_records_default_state(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    turn_context: dict[str, object] = {}

    bridge.trace_canonical_planning_prepared(
        turn_context,
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )

    trace = turn_context["canonical_planning_provider"]
    assert trace["default_enabled"] is True
    assert trace["env_value"] is None
    assert trace["result"] == "prepared"


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


def test_canonical_planning_provider_allows_health_sidecar_memory_signal(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    signal = UserSignal(
        type="health",
        label="fatigue",
        status="new",
        severity="medium",
        confidence=0.9,
        evidence="Je suis fatigue",
        payload={
            "action_type": "record_health_signal",
            "status": "fatigue",
            "body_part": None,
            "severity": "medium",
        },
    )

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(kind="lighten", source_ref="session_id:1", target_ref=None),
            signals=(signal,),
        ),
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


def test_canonical_planning_provider_allows_implicit_planning_preference_sidecar(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    signal = UserSignal(
        type="preference",
        label="swap_request",
        status="new",
        severity="low",
        confidence=0.9,
        evidence="Echange mercredi et jeudi si c'est mieux sportivement",
        payload={
            "preference": "Echanger les seances de mercredi et jeudi pour optimisation sportive",
            "polarity": "prefer",
            "scope": "day",
            "target_ref": "mercredi_et_jeudi",
        },
    )

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(
                kind="swap",
                source_ref="date:2026-05-20",
                target_ref="date:2026-05-21",
            ),
            signals=(signal,),
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )


def test_canonical_planning_provider_allows_sport_preference_sidecar_for_replace(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    signal = UserSignal(
        type="preference",
        label="replace_swimming_with_cycling",
        status="new",
        severity="unknown",
        confidence=0.95,
        evidence="Remplace la natation dimanche par un velo facile",
        payload={
            "action_type": "record_preference",
            "preference": "velo facile instead of natation",
            "polarity": "prefer",
            "scope": "sport",
            "sport_type": "cycling",
            "target_ref": "2026-05-24",
        },
    )

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(
                kind="replace",
                source_ref="date:2026-05-24",
                target_ref="date:2026-05-24",
                desired_sport="velo",
            ),
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


def test_unsupported_canonical_planning_change_blocks_without_legacy_fallthrough(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_PLANNING_PROVIDER", "1")
    understanding = _understanding(
        requested_change=_requested_change(
            kind="move",
            source_ref=None,
            target_ref="later_in_week",
            desired_sport="running",
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="plan_mutation",
        secondary_intents=(),
        planning_action="move_session",
        user_goal="mettre la course plus tard dans la semaine",
        confidence=0.8,
        temporal_references=(),
    )

    assert bridge.should_handle_unsupported_canonical_planning_without_legacy(
        understanding=understanding,
        turn_plan=turn_plan,
        pending_confirmation=None,
    )

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "plan_blocked"
            assert "plan_committed" in outcome.reply_contract.forbidden_claims
            return SimpleNamespace(text=outcome.explanation.reason_summary, verified=True)

    turn_context: dict[str, object] = {}
    outcome = bridge.handle_canonical_planning(
        understanding=understanding,
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="Mets la course plus tard dans la semaine.",
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
