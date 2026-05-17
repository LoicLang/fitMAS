from __future__ import annotations

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
    ) -> AdaptationPolicyDecision:
        return decide_adaptation_policy(evaluated_candidates, reviewer_decision=reviewer_decision)
