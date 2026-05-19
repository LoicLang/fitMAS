from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy.planning_outcome_adapter import planning_decision_to_outcome
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def _decision(kind: str, *, command_result: PlanningCommandResult | None = None) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,  # type: ignore[arg-type]
        selected_candidate_id="cand_1",
        candidate_options=("cand_1", "cand_2") if kind == "pending_choice" else (),
        reason="Option possible, confirmation recommandee.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=None,
        evaluated_candidates=(SimpleNamespace(candidate=SimpleNamespace(id="cand_1", rationale="move friday")),),
        command_result=command_result,
        pending_confirmation_id=44 if kind.startswith("pending") else None,
    )


def test_adapter_maps_commit_to_plan_committed_outcome() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "commit",
            command_result=PlanningCommandResult(
                status="applied",
                event_count=1,
                pending_confirmation_id=None,
                service_result=None,
                payload={"summary": "Footing deplace vendredi.", "event_id": "evt_1"},
            ),
        )
    )

    assert outcome.kind == "plan_committed"
    assert outcome.applied_commands[0].event_id == "evt_1"
    assert outcome.reply_contract.allowed_claims == ("plan_committed",)


def test_adapter_blocks_commit_without_applied_event_evidence() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "commit",
            command_result=PlanningCommandResult(
                status="blocked",
                event_count=0,
                pending_confirmation_id=None,
                service_result=None,
                payload={"reason": "no_event"},
            ),
        )
    )

    assert outcome.kind == "plan_blocked"
    assert outcome.applied_commands == ()
    assert "plan_committed" in outcome.reply_contract.forbidden_claims


def test_adapter_blocks_pending_without_pending_id() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "pending_confirmation",
            command_result=PlanningCommandResult(
                status="blocked",
                event_count=0,
                pending_confirmation_id=None,
                service_result=None,
                payload={"reason": "missing_pending_id"},
            ),
        )
    )

    assert outcome.kind == "plan_blocked"
    assert outcome.reply_contract.allowed_claims == ()
    assert "plan_committed" in outcome.reply_contract.forbidden_claims


def test_adapter_maps_pending_choice_to_plan_choice_pending() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "pending_choice",
            command_result=PlanningCommandResult(
                status="pending",
                event_count=0,
                pending_confirmation_id=44,
                service_result=None,
                payload={"candidate_options": ("cand_1", "cand_2")},
            ),
        )
    )

    assert outcome.kind == "plan_choice_pending"
    assert outcome.reply_contract.forbidden_claims == ("plan_committed",)
    assert outcome.explanation.next_step == "Choisis l'option que tu veux garder."


def test_adapter_maps_block_to_plan_blocked_without_applied_commands() -> None:
    outcome = planning_decision_to_outcome(_decision("block"))

    assert outcome.kind == "plan_blocked"
    assert outcome.applied_commands == ()
    assert outcome.explanation.reason_summary == "Option possible, confirmation recommandee."


def test_adapter_does_not_expose_backend_candidate_ids_to_reply_context() -> None:
    decision = PlanningDecisionResult(
        kind="pending_confirmation",
        selected_candidate_id="backend:replace_session:4:mobility_30",
        candidate_options=(),
        reason="Option possible, confirmation recommandee.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=None,
        evaluated_candidates=(
            SimpleNamespace(
                candidate=SimpleNamespace(
                    id="backend:replace_session:4:mobility_30",
                    rationale="Remplacer la natation par recuperation active.",
                )
            ),
        ),
        command_result=PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=44,
            service_result=None,
            payload={"selected_candidate_id": "backend:replace_session:4:mobility_30"},
        ),
        pending_confirmation_id=44,
    )

    outcome = planning_decision_to_outcome(decision)

    assert outcome.candidates == ("Remplacer la natation par recuperation active.",)


def test_adapter_exposes_selected_patch_operation_summary_before_llm_rationale() -> None:
    decision = PlanningDecisionResult(
        kind="pending_confirmation",
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Option possible, confirmation recommandee.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=PlanPatch(
            coach_message="patch",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=3,
                    target_date="2026-05-25",
                    rationale="move",
                ),
            ),
        ),
        evaluated_candidates=(
            SimpleNamespace(candidate=SimpleNamespace(id="cand_1", rationale="Option vague avec jeudi")),
        ),
        command_result=PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=44,
            service_result=None,
            payload={"selected_candidate_id": "cand_1"},
        ),
        pending_confirmation_id=44,
    )

    outcome = planning_decision_to_outcome(decision)

    assert outcome.candidates[0] == "deplacer la seance ciblee au 2026-05-25 (lundi)"


def test_adapter_exposes_multi_move_patch_as_one_user_safe_summary() -> None:
    decision = PlanningDecisionResult(
        kind="pending_confirmation",
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Fenetre large: confirmation requise avant de deplacer plusieurs seances.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=PlanPatch(
            coach_message="patch",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=1,
                    target_date="2026-05-23",
                    rationale="travel",
                ),
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=2,
                    target_date="2026-05-25",
                    rationale="travel",
                ),
            ),
        ),
        evaluated_candidates=(
            SimpleNamespace(candidate=SimpleNamespace(id="cand_1", rationale="Option vague")),
        ),
        command_result=PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=44,
            service_result=None,
            payload={"selected_candidate_id": "cand_1"},
        ),
        pending_confirmation_id=44,
    )

    outcome = planning_decision_to_outcome(decision)

    assert outcome.candidates[0] == (
        "deplacer les 2 seances touchees apres la fenetre, en gardant leur ordre: "
        "2026-05-23 (samedi), puis 2026-05-25 (lundi)"
    )
    assert len(tuple(candidate for candidate in outcome.candidates if "move_session" in candidate)) == 0
    assert outcome.explanation.impact["operation_count"] == 2
    assert outcome.explanation.impact["move_session_count"] == 2
    assert outcome.explanation.impact["target_dates"] == ("2026-05-23", "2026-05-25")
    assert outcome.explanation.impact["requires_confirmation"] is True


def test_adapter_exposes_replace_operation_sport_duration_and_intensity() -> None:
    decision = PlanningDecisionResult(
        kind="pending_confirmation",
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Option possible, confirmation recommandee.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=PlanPatch(
            coach_message="patch",
            operations=(
                PlanPatchOperation(
                    operation_type="replace_session",
                    target_session_id=4,
                    new_sport_type="cycling",
                    new_duration_min=30,
                    new_intensity="easy",
                    rationale="replace",
                ),
            ),
        ),
        evaluated_candidates=(),
        command_result=PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=44,
            service_result=None,
            payload={"selected_candidate_id": "cand_1"},
        ),
        pending_confirmation_id=44,
    )

    outcome = planning_decision_to_outcome(decision)

    assert outcome.candidates[0] == (
        "replace_session | target_session_id=4 | new_sport_type=cycling | "
        "new_duration_min=30 | new_intensity=easy"
    )
