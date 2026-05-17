from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas.domain.planning.models import PlanningCandidateSet
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate, evaluate_plan_patch_candidate
from fitmas.plan_patch_candidates import ALLOWED_CANDIDATE_OPERATION_TYPES


class PlanCandidateEvaluator:
    def __init__(self, *, db: Session, user: Any):
        self._db = db
        self._user = user

    def evaluate(
        self,
        candidate_set: PlanningCandidateSet,
        *,
        scheduled_sessions: Sequence[Any],
        activities: Sequence[Any],
        active_facts: Sequence[Any],
        coach_state_bundle: Any | None,
    ) -> tuple[EvaluatedPlanPatchCandidate, ...]:
        return tuple(
            evaluate_plan_patch_candidate(
                self._db,
                candidate=candidate,
                current_plan_id="plan_current",
                current_plan_version=1,
                plan_id=0,
                scheduled_sessions=scheduled_sessions,
                current_score=None,
                timezone_name=getattr(self._user, "timezone", None),
                allowed_operations=tuple(ALLOWED_CANDIDATE_OPERATION_TYPES),
                backend_candidate_patches=candidate_set.backend_candidate_patches,
                coach_state_bundle=coach_state_bundle,
                activities=activities,
                active_facts=active_facts,
            )
            for candidate in candidate_set.candidates
        )
