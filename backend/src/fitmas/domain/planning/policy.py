from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Sequence

from fitmas.domain.planning.evaluator import EvaluatedPlanPatchCandidate
from fitmas.domain.planning.reviewer import PlanPatchCandidateReviewDecision

AdaptationPolicyAction = Literal["commit", "pending_confirmation", "pending_choice", "block"]
RiskLevel = Literal["low", "medium", "high"]

_CLOSE_SCORE_MARGIN = 5.0
_LARGE_SCORE_DEGRADATION = -15.0


@dataclass(frozen=True, slots=True)
class AdaptationPolicyDecision:
    action: AdaptationPolicyAction
    selected_candidate_id: str | None
    candidate_options: tuple[str, ...]
    reason: str
    user_facing_reason: str
    requires_confirmation_reason: str | None
    risk_level: RiskLevel
    committed_events: tuple[dict[str, Any], ...] = ()
    pending_event: dict[str, Any] | None = None


def decide_adaptation_policy(
    evaluated_candidates: Sequence[EvaluatedPlanPatchCandidate],
    *,
    reviewer_decision: PlanPatchCandidateReviewDecision | None = None,
) -> AdaptationPolicyDecision:
    """Choose commit/pending/block from already evaluated PlanPatch candidates.

    This layer never parses user text and never writes. It only takes
    responsibility for structured artifacts produced by the candidate evaluator.
    """
    usable = sorted(
        (candidate for candidate in evaluated_candidates if _is_usable(candidate)),
        key=_score_total,
        reverse=True,
    )
    if not usable:
        return _block_decision("Aucune option d'adaptation valide.")

    reviewer_choice = _reviewer_choice(usable, reviewer_decision=reviewer_decision)
    if reviewer_choice is not None:
        return _decision_for_best(
            reviewer_choice,
            reason_override="Option choisie par reviewer borne.",
        )

    close_candidates = _close_candidates(usable)
    if len(close_candidates) > 1:
        reason = "Plusieurs options valides sont proches avec des compromis differents."
        candidate_ids = tuple(candidate.candidate.id for candidate in close_candidates)
        return AdaptationPolicyDecision(
            action="pending_choice",
            selected_candidate_id=None,
            candidate_options=candidate_ids,
            reason=reason,
            user_facing_reason=reason,
            requires_confirmation_reason=reason,
            risk_level="medium",
            pending_event={
                "candidate_ids": candidate_ids,
                "reason": reason,
                "risk_level": "medium",
            },
        )

    return _decision_for_best(usable[0])


def _decision_for_best(
    best: EvaluatedPlanPatchCandidate,
    *,
    reason_override: str | None = None,
) -> AdaptationPolicyDecision:
    risk_level = _risk_level(best)
    if risk_level != "low" or best.policy_hint == "ask_confirmation":
        reason = _confirmation_reason(best)
        return AdaptationPolicyDecision(
            action="pending_confirmation",
            selected_candidate_id=best.candidate.id,
            candidate_options=(),
            reason=reason,
            user_facing_reason=reason,
            requires_confirmation_reason=reason,
            risk_level=risk_level,
            pending_event={
                "candidate_id": best.candidate.id,
                "reason": reason,
                "risk_level": risk_level,
            },
        )

    return AdaptationPolicyDecision(
        action="commit",
        selected_candidate_id=best.candidate.id,
        candidate_options=(),
        reason=reason_override or "Option valide a basse friction.",
        user_facing_reason=reason_override or "Option valide a basse friction.",
        requires_confirmation_reason=None,
        risk_level="low",
    )


def _is_usable(candidate: EvaluatedPlanPatchCandidate) -> bool:
    if candidate.candidate_validation.status == "blocked":
        return False
    if candidate.policy_hint == "block":
        return False
    if candidate.patch_validation is None or candidate.patch_validation.status == "blocked":
        return False
    if candidate.score is None:
        return False
    return True


def _score_total(candidate: EvaluatedPlanPatchCandidate) -> float:
    return candidate.score.total if candidate.score is not None else -999.0


def _close_candidates(
    usable: Sequence[EvaluatedPlanPatchCandidate],
) -> tuple[EvaluatedPlanPatchCandidate, ...]:
    if len(usable) < 2:
        return ()
    top_score = _score_total(usable[0])
    close = [
        candidate
        for candidate in usable
        if top_score - _score_total(candidate) < _CLOSE_SCORE_MARGIN
    ]
    return tuple(close[:3])


def _reviewer_choice(
    usable: Sequence[EvaluatedPlanPatchCandidate],
    *,
    reviewer_decision: PlanPatchCandidateReviewDecision | None,
) -> EvaluatedPlanPatchCandidate | None:
    if reviewer_decision is None or reviewer_decision.confidence < 0.6:
        return None
    top_score = _score_total(usable[0])
    selected = next(
        (
            candidate
            for candidate in usable
            if candidate.candidate.id == reviewer_decision.preferred_candidate_id
        ),
        None,
    )
    if selected is None:
        return None
    if top_score - _score_total(selected) > 8.0:
        return None
    return selected


def _risk_level(candidate: EvaluatedPlanPatchCandidate) -> RiskLevel:
    if candidate.policy_hint == "block":
        return "high"
    if any(finding.severity == "blocker" for finding in candidate.findings):
        return "high"
    if candidate.policy_hint == "ask_confirmation":
        return "medium"
    if any(finding.severity in {"risk", "warning"} for finding in candidate.findings):
        return "medium"
    if candidate.score_delta is not None and candidate.score_delta <= _LARGE_SCORE_DEGRADATION:
        return "medium"
    if candidate.patch_validation is not None and candidate.patch_validation.status in {
        "warning",
        "requires_confirmation",
    }:
        return "medium"
    return "low"


def _confirmation_reason(candidate: EvaluatedPlanPatchCandidate) -> str:
    if candidate.evaluation_summary:
        return candidate.evaluation_summary
    if candidate.score_delta is not None:
        return f"Option possible, mais elle change la coherence de la semaine (score_delta={candidate.score_delta})."
    return "Option possible, mais elle merite confirmation."


def _block_decision(reason: str) -> AdaptationPolicyDecision:
    return AdaptationPolicyDecision(
        action="block",
        selected_candidate_id=None,
        candidate_options=(),
        reason=reason,
        user_facing_reason=reason,
        requires_confirmation_reason=None,
        risk_level="high",
    )


class SportPolicy:
    def decide(
        self,
        evaluated_candidates: Sequence[EvaluatedPlanPatchCandidate],
        *,
        reviewer_decision: PlanPatchCandidateReviewDecision | None = None,
        force_confirmation_reason: str | None = None,
    ) -> AdaptationPolicyDecision:
        decision = decide_adaptation_policy(evaluated_candidates, reviewer_decision=reviewer_decision)
        if force_confirmation_reason is None or decision.selected_candidate_id is None:
            return decision
        return replace(
            decision,
            action="pending_confirmation",
            reason=force_confirmation_reason,
            user_facing_reason=force_confirmation_reason,
            requires_confirmation_reason=force_confirmation_reason,
            risk_level="medium",
            pending_event={
                "candidate_id": decision.selected_candidate_id,
                "reason": force_confirmation_reason,
                "risk_level": "medium",
            },
        )
