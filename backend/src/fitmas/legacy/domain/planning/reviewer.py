from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from fitmas.legacy.llm.prompts.reviewer import ReviewerPromptCandidate, build_reviewer_prompt
from fitmas.legacy.domain.planning.evaluator import EvaluatedPlanPatchCandidate

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
        rendered = build_reviewer_prompt(tuple(_reviewer_candidate_payload(candidate) for candidate in reviewable))
        payload = request_json_fn(
            system=rendered.system,
            prompt=rendered.prompt,
            max_tokens=rendered.max_tokens,
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


def _reviewer_candidate_payload(candidate: EvaluatedPlanPatchCandidate) -> ReviewerPromptCandidate:
    return ReviewerPromptCandidate(
        candidate_id=candidate.candidate.id,
        rationale=candidate.candidate.rationale,
        expected_tradeoff=candidate.candidate.expected_tradeoff,
        score_total=candidate.score.total if candidate.score is not None else None,
        score_delta=candidate.score_delta,
        policy_hint=candidate.policy_hint,
        findings=tuple(f"{finding.code}: {finding.severity}: {finding.message}" for finding in candidate.findings),
        operations=tuple(
            " | ".join(
                str(part)
                for part in (
                    operation.operation_type,
                    f"target_session_id={operation.target_session_id}" if operation.target_session_id is not None else "",
                    f"second_session_id={operation.second_session_id}" if operation.second_session_id is not None else "",
                    f"target_date={operation.target_date}" if operation.target_date else "",
                    f"new_sport_type={operation.new_sport_type}" if operation.new_sport_type else "",
                    f"new_session_type={operation.new_session_type}" if operation.new_session_type else "",
                    f"new_duration_min={operation.new_duration_min}" if operation.new_duration_min is not None else "",
                    f"new_intensity={operation.new_intensity}" if operation.new_intensity else "",
                )
                if part
            )
            for operation in (candidate.patch.operations if candidate.patch is not None else ())
        ),
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
