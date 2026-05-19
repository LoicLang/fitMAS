from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision, decide_adaptation_policy
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidate_reviewer import PlanPatchCandidateReviewDecision


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
