from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange, UserSignal
from fitmas.legacy.coach_command_adapter import (
    commands_from_legacy_decision,
    commands_from_understanding,
    execution_action_from_command,
    memory_action_from_command,
)
from fitmas.legacy.decision_contracts import AvailabilityConstraintAction, CoachDecision, ExecutionUpdateAction, HealthSignalAction


def test_legacy_decision_memory_and_execution_actions_become_commands() -> None:
    decision = CoachDecision(
        response_type="reply",
        rationale="typed actions should become commands",
        fitmas_message="ok",
        memory_actions=(
            HealthSignalAction(
                type="record_health_signal",
                health_signal="douleur genou",
                body_area="genou",
                status="ongoing",
                severity="moderate",
                signal_kind="pain",
                confidence=0.9,
                evidence="mal au genou",
            ),
        ),
        execution_actions=(
            ExecutionUpdateAction(
                type="record_execution_update",
                target_ref="2026-05-13",
                status="not_completed",
                completed=False,
                sport_type="strength",
                confidence=0.9,
                evidence="pas fait",
            ),
        ),
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=None)

    assert [command.domain for command in bundle.commands] == ["memory", "execution"]
    assert bundle.deferred_execution_count == 0
    assert memory_action_from_command(bundle.commands[0]).type == "record_health_signal"
    assert execution_action_from_command(bundle.commands[1]).type == "record_execution_update"


def test_turn_plan_availability_is_added_once_to_legacy_commands() -> None:
    decision = CoachDecision(
        response_type="reply",
        rationale="turn plan availability should become memory command",
        fitmas_message="ok",
    )
    turn_plan = SimpleNamespace(
        availability_constraint={
            "availability": "unavailable",
            "sport_type": "swimming",
            "scope": "sport",
            "starts_on": "2026-05-14",
            "ends_on": "2026-05-28",
        },
        confidence=0.82,
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=turn_plan)

    assert len(bundle.commands) == 1
    action = memory_action_from_command(bundle.commands[0])
    assert isinstance(action, AvailabilityConstraintAction)
    assert action.availability == "unavailable"
    assert action.sport_type == "swimming"
    assert action.starts_on == "2026-05-14"
    assert action.ends_on == "2026-05-28"


def test_conflicting_execution_action_is_deferred_when_plan_patch_targets_same_session() -> None:
    execution_action = ExecutionUpdateAction(
        type="record_execution_update",
        target_ref="seance cible",
        target_session_id=42,
        status="not_completed",
        completed=False,
        confidence=0.9,
        evidence="pas fait",
    )
    availability_action = AvailabilityConstraintAction(
        type="record_availability",
        window_text="indispo",
        availability="unavailable",
        starts_on="2026-05-14",
        ends_on="2026-05-14",
        confidence=0.9,
        evidence="indispo",
    )
    patch = SimpleNamespace(operations=(SimpleNamespace(target_session_id=42),))
    decision = CoachDecision(
        response_type="requires_confirmation",
        rationale="availability plus plan patch should defer matching execution action",
        fitmas_message="ok",
        plan_patch=patch,
        memory_actions=(availability_action,),
        execution_actions=(execution_action,),
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=None)

    assert [command.domain for command in bundle.commands] == ["memory"]
    assert bundle.deferred_execution_count == 1


def test_understanding_signals_compile_to_commands_from_payload_only() -> None:
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="piscine impossible deux semaines",
        extracted_signals=(
            UserSignal(
                type="availability",
                label="natation indisponible",
                status="new",
                severity="high",
                confidence=0.91,
                evidence="je ne peux pas nager deux semaines",
                payload={
                    "action_type": "record_availability",
                    "availability": "unavailable",
                    "window_text": "natation impossible deux semaines",
                    "sport_type": "swimming",
                    "scope": "sport",
                    "starts_on": "2026-05-14",
                    "ends_on": "2026-05-28",
                },
            ),
        ),
        requested_change=RequestedPlanChange(
            kind="unknown",
            source_ref=None,
            target_ref=None,
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity=None,
            reason="availability",
            risk_signals=(),
        ),
        pending_resolution=None,
        clarification_need=None,
    )

    bundle = commands_from_understanding(understanding)

    assert len(bundle.commands) == 1
    action = memory_action_from_command(bundle.commands[0])
    assert isinstance(action, AvailabilityConstraintAction)
    assert action.availability == "unavailable"
    assert action.sport_type == "swimming"
