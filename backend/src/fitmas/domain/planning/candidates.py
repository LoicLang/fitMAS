from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from fitmas.plan_patch import PlanPatch

PlanPatchCandidateValidationStatus = Literal["valid", "blocked"]

ALLOWED_CANDIDATE_OPERATION_TYPES: frozenset[str] = frozenset(
    {
        "move_session",
        "swap_sessions",
        "replace_session",
        "update_session",
        "lighten_day",
        "create_session",
    }
)


@dataclass(frozen=True, slots=True)
class PlanPatchCandidate:
    id: str
    patches: tuple[PlanPatch, ...]
    rationale: str
    expected_tradeoff: str
    confidence: float
    assumptions: tuple[str, ...]
    risk_notes: tuple[str, ...]
    created_from_plan_id: str
    created_from_plan_version: int
    candidate_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PlanPatchCandidateOperationValidation:
    operation_type: str
    status: PlanPatchCandidateValidationStatus
    patch_index: int
    operation_index: int
    block_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlanPatchCandidateValidation:
    status: PlanPatchCandidateValidationStatus
    patch_count: int
    operation_count: int
    operation_results: tuple[PlanPatchCandidateOperationValidation, ...]
    block_reason: str | None = None
    summary: str = ""
    commit_performed: bool = False


def validate_plan_patch_candidate_contract(
    candidate: PlanPatchCandidate,
    *,
    current_plan_id: str,
    current_plan_version: int,
    allowed_operations: Sequence[str] | None = None,
) -> PlanPatchCandidateValidation:
    """Validate a candidate patch set contract. This function never writes."""
    operation_results = _validate_candidate_operations(
        candidate,
        allowed_operations=frozenset(allowed_operations or ALLOWED_CANDIDATE_OPERATION_TYPES),
    )
    patch_count = len(candidate.patches)
    operation_count = len(operation_results)
    candidate_ref = str(candidate.candidate_ref or "").strip()

    if str(candidate.created_from_plan_id) != str(current_plan_id):
        return _blocked_validation(
            "stale_plan_id",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    if int(candidate.created_from_plan_version) != int(current_plan_version):
        return _blocked_validation(
            "stale_plan_version",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    if candidate.confidence < 0 or candidate.confidence > 1:
        return _blocked_validation(
            "invalid_confidence",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    if candidate_ref and patch_count > 0:
        return _blocked_validation(
            "ambiguous_candidate_ref",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    if not candidate_ref and (patch_count == 0 or operation_count == 0):
        return _blocked_validation(
            "empty_candidate",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    blocked_operation = next((result for result in operation_results if result.status == "blocked"), None)
    if blocked_operation is not None:
        return _blocked_validation(
            blocked_operation.block_reason or "operation_blocked",
            patch_count=patch_count,
            operation_count=operation_count,
            operation_results=operation_results,
        )
    return PlanPatchCandidateValidation(
        status="valid",
        patch_count=patch_count,
        operation_count=operation_count,
        operation_results=operation_results,
        summary=(
            f"Candidate ref valide: {candidate_ref}."
            if candidate_ref
            else f"Candidate valide: {patch_count} patch(es), {operation_count} operation(s)."
        ),
        commit_performed=False,
    )


def _validate_candidate_operations(
    candidate: PlanPatchCandidate,
    *,
    allowed_operations: frozenset[str],
) -> tuple[PlanPatchCandidateOperationValidation, ...]:
    results: list[PlanPatchCandidateOperationValidation] = []
    for patch_index, patch in enumerate(candidate.patches):
        for operation_index, operation in enumerate(patch.operations):
            operation_type = str(getattr(operation, "operation_type", "") or "")
            if operation_type not in allowed_operations:
                results.append(
                    PlanPatchCandidateOperationValidation(
                        operation_type=operation_type,
                        status="blocked",
                        patch_index=patch_index,
                        operation_index=operation_index,
                        block_reason="operation_not_allowed",
                    )
                )
                continue
            results.append(
                PlanPatchCandidateOperationValidation(
                    operation_type=operation_type,
                    status="valid",
                    patch_index=patch_index,
                    operation_index=operation_index,
                )
            )
    return tuple(results)


def _blocked_validation(
    reason: str,
    *,
    patch_count: int,
    operation_count: int,
    operation_results: tuple[PlanPatchCandidateOperationValidation, ...],
) -> PlanPatchCandidateValidation:
    return PlanPatchCandidateValidation(
        status="blocked",
        patch_count=patch_count,
        operation_count=operation_count,
        operation_results=operation_results,
        block_reason=reason,
        summary=f"Option bloquee: {reason}.",
        commit_performed=False,
    )
