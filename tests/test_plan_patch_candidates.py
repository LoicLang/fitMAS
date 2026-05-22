from __future__ import annotations

from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.domain.planning.candidates import (
    PlanPatchCandidate,
    validate_plan_patch_candidate_contract,
)


def test_plan_patch_candidate_accepts_patch_set_without_writing_or_committing() -> None:
    candidate = PlanPatchCandidate(
        id="cand_move_and_reduce",
        patches=(
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=42,
                        target_date="2099-05-08",
                        rationale="Nouveau creneau utilisateur.",
                    )
                ],
                coach_message="Option candidate, pas une reponse finale.",
            ),
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="update_session",
                        target_session_id=43,
                        new_duration_min=30,
                        new_intensity="easy",
                        rationale="Reduire la charge apres le deplacement.",
                    )
                ],
                coach_message="Option candidate, pas une reponse finale.",
            ),
        ),
        rationale="Deplacer la seance demandee et alleger la suivante.",
        expected_tradeoff="Recuperation preservee, volume hebdo un peu reduit.",
        confidence=0.82,
        assumptions=("Le user parle bien de la seance 42.",),
        risk_notes=("A valider contre la semaine simulee.",),
        created_from_plan_id="plan_123",
        created_from_plan_version=7,
    )

    validation = validate_plan_patch_candidate_contract(
        candidate,
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert validation.status == "valid"
    assert validation.patch_count == 2
    assert validation.operation_count == 2
    assert validation.block_reason is None
    assert validation.commit_performed is False


def test_plan_patch_candidate_accepts_backend_candidate_ref_without_copied_patch() -> None:
    candidate = PlanPatchCandidate(
        id="cand_ref_move_friday",
        patches=(),
        candidate_ref="backend:move_session:42:2099-05-08",
        rationale="Choisir l'option backend deja materialisee.",
        expected_tradeoff="Le backend simulera la vraie semaine avant commit.",
        confidence=0.86,
        assumptions=("Le user valide cette option.",),
        risk_notes=(),
        created_from_plan_id="plan_123",
        created_from_plan_version=7,
    )

    validation = validate_plan_patch_candidate_contract(
        candidate,
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert validation.status == "valid"
    assert validation.patch_count == 0
    assert validation.operation_count == 0
    assert validation.block_reason is None
    assert validation.commit_performed is False


def test_plan_patch_candidate_blocks_stale_plan_version() -> None:
    candidate = _candidate(created_from_plan_version=6)

    validation = validate_plan_patch_candidate_contract(
        candidate,
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert validation.status == "blocked"
    assert validation.block_reason == "stale_plan_version"
    assert validation.commit_performed is False


def test_plan_patch_candidate_blocks_unknown_operation_even_if_payload_bypassed_schema() -> None:
    invalid_operation = PlanPatchOperation.model_construct(
        operation_type="add_hard_session",
        target_session_id=42,
        rationale="Operation hors Phase A.",
    )
    candidate = _candidate(
        patches=(
            PlanPatch.model_construct(
                operations=[invalid_operation],
                coach_message="Option candidate.",
                confirmation_reason=None,
            ),
        )
    )

    validation = validate_plan_patch_candidate_contract(
        candidate,
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert validation.status == "blocked"
    assert validation.block_reason == "operation_not_allowed"
    assert validation.operation_results[0].operation_type == "add_hard_session"
    assert validation.operation_results[0].status == "blocked"


def test_plan_patch_candidate_blocks_empty_or_low_confidence_candidate() -> None:
    empty = _candidate(patches=())
    low_confidence = _candidate(confidence=-0.1)

    empty_validation = validate_plan_patch_candidate_contract(
        empty,
        current_plan_id="plan_123",
        current_plan_version=7,
    )
    low_confidence_validation = validate_plan_patch_candidate_contract(
        low_confidence,
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert empty_validation.status == "blocked"
    assert empty_validation.block_reason == "empty_candidate"
    assert low_confidence_validation.status == "blocked"
    assert low_confidence_validation.block_reason == "invalid_confidence"


def test_plan_patch_candidate_blocks_candidate_ref_mixed_with_copied_patch() -> None:
    validation = validate_plan_patch_candidate_contract(
        _candidate(candidate_ref="backend:move_session:42:2099-05-08"),
        current_plan_id="plan_123",
        current_plan_version=7,
    )

    assert validation.status == "blocked"
    assert validation.block_reason == "ambiguous_candidate_ref"


def _candidate(
    *,
    patches: tuple[PlanPatch, ...] | None = None,
    confidence: float = 0.8,
    created_from_plan_version: int = 7,
    candidate_ref: str | None = None,
) -> PlanPatchCandidate:
    if patches is None:
        patches = (
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=42,
                        target_date="2099-05-08",
                        rationale="Nouveau creneau utilisateur.",
                    )
                ],
                coach_message="Option candidate.",
            ),
        )
    return PlanPatchCandidate(
        id="cand_1",
        patches=patches,
        candidate_ref=candidate_ref,
        rationale="Option de changement.",
        expected_tradeoff="Compromis a evaluer.",
        confidence=confidence,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_123",
        created_from_plan_version=created_from_plan_version,
    )
