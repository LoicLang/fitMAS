from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision.planning_outcomes import plan_patch_service_result_to_outcome
from fitmas.plan_mutation_service import PlanPatchServiceResult
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchOperationValidation, PlanPatchValidation


def _patch() -> PlanPatch:
    return PlanPatch(
        coach_message="Je deplace la seance.",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-15",
                rationale="move",
            )
        ],
    )


def test_adapter_maps_applied_service_result_to_committed_outcome() -> None:
    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        patch=_patch(),
        mutation_result=SimpleNamespace(
            applied_events=(SimpleNamespace(user_visible_summary="Footing deplace vendredi.", id=123),),
            blocked_events=(),
        ),
    )

    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")

    assert outcome.kind == "plan_committed"
    assert outcome.applied_commands[0].payload["summary"] == "Footing deplace vendredi."


def test_adapter_prefers_directional_move_summary_from_event_snapshots() -> None:
    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        patch=_patch(),
        mutation_result=SimpleNamespace(
            applied_events=(
                SimpleNamespace(
                    command_type="move_session",
                    user_visible_summary="Vendredi: Recuperation mobilite.",
                    id=123,
                    before_snapshot={
                        "session_title": "Recuperation mobilite",
                        "scheduled_date": "2026-05-29",
                    },
                    after_snapshot={
                        "session_title": "Recuperation mobilite",
                        "scheduled_date": "2026-05-25",
                    },
                ),
            ),
            blocked_events=(),
        ),
    )

    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")

    assert outcome.applied_commands[0].payload["summary"] == (
        "J'ai deplace Recuperation mobilite du 2026-05-29 (vendredi) au 2026-05-25 (lundi)."
    )


def test_adapter_maps_requires_confirmation_to_pending_outcome() -> None:
    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(
            status="requires_confirmation",
            operation_results=(
                PlanPatchOperationValidation(
                    operation_type="move_session",
                    status="requires_confirmation",
                    warning_messages=("Ce changement modifie la semaine.",),
                ),
            ),
            summary="confirm",
        ),
        patch=_patch(),
    )

    outcome = plan_patch_service_result_to_outcome(service_result, mode="pending")

    assert outcome.kind == "plan_pending"
    assert outcome.reply_contract.forbidden_claims == ("plan_committed",)
    assert "Ce changement modifie la semaine." in outcome.explanation.reason_summary
