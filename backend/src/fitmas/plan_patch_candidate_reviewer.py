from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate

RequestJsonFn = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class PlanPatchCandidateReviewDecision:
    preferred_candidate_id: str
    confidence: float
    rationale: tuple[str, ...]


def review_plan_patch_candidates(
    evaluated_candidates: Sequence[EvaluatedPlanPatchCandidate],
    *,
    request_json_fn: RequestJsonFn,
) -> PlanPatchCandidateReviewDecision | None:
    reviewable = [candidate for candidate in evaluated_candidates if _is_reviewable(candidate)]
    if len(reviewable) < 2:
        return None
    candidate_ids = {candidate.candidate.id for candidate in reviewable}
    try:
        payload = request_json_fn(
            system=_reviewer_system(),
            prompt=_reviewer_prompt(reviewable),
            max_tokens=600,
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    preferred_id = str(payload.get("preferred_candidate_id") or "").strip()
    if preferred_id not in candidate_ids:
        return None
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 1:
        return None
    rationale = _string_tuple(payload.get("rationale"))
    return PlanPatchCandidateReviewDecision(
        preferred_candidate_id=preferred_id,
        confidence=confidence,
        rationale=rationale,
    )


def _reviewer_system() -> str:
    return (
        "Tu es BackendPlanPatchCandidateReviewer. "
        "You return candidate_id only; never return patches, operations, JSON PlanPatch, or user-facing text. "
        "Tu choisis uniquement parmi les candidate_id fournis."
    )


def _reviewer_prompt(evaluated_candidates: Sequence[EvaluatedPlanPatchCandidate]) -> str:
    context = {
        "candidates": [_candidate_payload(candidate) for candidate in evaluated_candidates],
        "output_contract": {
            "preferred_candidate_id": "one of candidates[].candidate_id",
            "confidence": "0..1",
            "rationale": ["short reasons based only on candidate facts"],
        },
    }
    return (
        "Choisis le meilleur compromis humain parmi ces candidates deja validees/scorées. "
        "N'invente aucune option. Ne produis aucun patch.\n\n"
        f"Contexte JSON:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )


def _candidate_payload(candidate: EvaluatedPlanPatchCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate.id,
        "rationale": candidate.candidate.rationale,
        "expected_tradeoff": candidate.candidate.expected_tradeoff,
        "score_total": candidate.score.total if candidate.score is not None else None,
        "score_delta": candidate.score_delta,
        "policy_hint": candidate.policy_hint,
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity,
                "message": finding.message,
            }
            for finding in candidate.findings
        ],
        "operations": _operation_summaries(candidate),
    }


def _operation_summaries(candidate: EvaluatedPlanPatchCandidate) -> tuple[dict[str, Any], ...]:
    if candidate.patch is None:
        return ()
    return tuple(
        {
            "operation_type": operation.operation_type,
            "target_session_id": operation.target_session_id,
            "second_session_id": operation.second_session_id,
            "target_date": operation.target_date,
            "new_sport_type": operation.new_sport_type,
            "new_session_type": operation.new_session_type,
            "new_duration_min": operation.new_duration_min,
            "new_intensity": operation.new_intensity,
        }
        for operation in candidate.patch.operations
    )


def _is_reviewable(candidate: EvaluatedPlanPatchCandidate) -> bool:
    if candidate.candidate_validation.status == "blocked":
        return False
    if candidate.policy_hint == "block":
        return False
    if candidate.patch_validation is None or candidate.patch_validation.status == "blocked":
        return False
    return candidate.score is not None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
