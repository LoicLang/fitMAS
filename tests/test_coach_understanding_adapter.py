from __future__ import annotations

from fitmas.legacy.coach_decision_artifact import LegacyCoachDecisionArtifact
from fitmas.legacy.coach_understanding_adapter import (
    coach_decision_artifact_to_understanding,
    coach_decision_to_understanding,
)
from fitmas.legacy.decision_contracts import (
    AcceptPendingResolution,
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    ModifyPendingResolution,
    MutationDecision,
)
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def test_adapter_maps_health_memory_action_without_visible_reply() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="fatigue signalee sans mutation",
        fitmas_message="Ancien message visible qui ne doit pas etre copie.",
        memory_actions=(
            HealthSignalAction(
                type="record_health_signal",
                health_signal="mauvais sommeil",
                signal_kind="sleep",
                severity="moderate",
                status="new",
                confidence=0.84,
                evidence="j'ai dormi 4h",
            ),
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "health_signal"
    assert understanding.user_summary == "fatigue signalee sans mutation"
    assert understanding.extracted_signals[0].type == "health"
    assert understanding.extracted_signals[0].label == "sleep"
    assert understanding.extracted_signals[0].payload["health_signal"] == "mauvais sommeil"
    assert "Ancien message visible" not in repr(understanding)


def test_adapter_maps_availability_and_execution_actions() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="disponibilite et execution captees",
        fitmas_message="Message legacy ignore.",
        memory_actions=(
            AvailabilityConstraintAction(
                type="record_availability",
                window_text="piscine fermee deux semaines",
                availability="unavailable",
                sport_type="swimming",
                starts_on="2026-05-14",
                ends_on="2026-05-28",
                confidence=0.8,
                evidence="piscine fermee",
            ),
        ),
        execution_actions=(
            ExecutionUpdateAction(
                type="record_execution_update",
                target_ref="seance d'hier",
                status="not_completed",
                completed=False,
                sport_type="running",
                confidence=0.79,
                evidence="je l'ai ratee",
            ),
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "execution_report"
    assert [signal.type for signal in understanding.extracted_signals] == ["availability", "execution"]
    assert understanding.extracted_signals[0].payload["sport_type"] == "swimming"
    assert understanding.extracted_signals[1].payload["target_ref"] == "seance d'hier"


def test_adapter_maps_pending_resolution() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="pending modifiee",
        fitmas_message="Message legacy ignore.",
        pending_resolution=ModifyPendingResolution(
            type="modify_pending",
            requested_changes="vendredi plutot que mercredi",
            reason="changement de disponibilite",
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "pending_response"
    assert understanding.pending_resolution is not None
    assert understanding.pending_resolution.type == "modify_pending"
    assert understanding.pending_resolution.requested_changes == "vendredi plutot que mercredi"


def test_adapter_maps_plan_patch_to_requested_change_without_carrying_patch() -> None:
    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement demande",
        fitmas_message="Message legacy ignore.",
        plan_patch=PlanPatch(
            coach_message="Message patch ignore.",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=42,
                    target_date="2026-05-15",
                    rationale="fatigue",
                ),
            ],
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "plan_change"
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "move"
    assert understanding.requested_change.source_ref == "session_id:42"
    assert understanding.requested_change.target_ref == "date:2026-05-15"
    assert "PlanPatch" not in repr(understanding)


def test_adapter_maps_legacy_mutation_decision_to_requested_change() -> None:
    decision = MutationDecision(
        mutation_type="lighten_day",
        target_session_id=7,
        target_date=None,
        from_day=None,
        to_day=None,
        rationale="fatigue",
        fitmas_message="Message legacy ignore.",
    )

    understanding = coach_decision_artifact_to_understanding(
        LegacyCoachDecisionArtifact(
            kind="coach_decision",
            response_type="mutation_decision",
            rationale="fatigue",
            mutation_decision=decision,
        )
    )

    assert understanding.intent == "plan_change"
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "lighten"
    assert understanding.requested_change.source_ref == "session_id:7"
    assert understanding.requested_change.reason == "fatigue"


def test_adapter_maps_accept_pending_candidate_choice() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="choix candidat",
        fitmas_message="Message legacy ignore.",
        pending_resolution=AcceptPendingResolution(
            type="accept_pending",
            reason="option choisie",
            selected_candidate_id="candidate_b",
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "pending_response"
    assert understanding.pending_resolution is not None
    assert understanding.pending_resolution.selected_candidate_id == "candidate_b"
