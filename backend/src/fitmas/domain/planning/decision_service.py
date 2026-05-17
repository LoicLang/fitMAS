from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.domain.planning.evaluator import PlanCandidateEvaluator
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.policy import SportPolicy
from fitmas.domain.planning.reference_resolver import ReferenceResolver
from fitmas.plan_patch_candidate_reviewer import review_plan_patch_candidates


def decide_plan_change(
    requested_change: RequestedPlanChange,
    *,
    context: Any,
    db: Session,
    user: Any,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningDecisionResult:
    resolved = ReferenceResolver(context).resolve(requested_change)
    if any(item.startswith("unresolved") for item in resolved.warnings):
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=", ".join(resolved.warnings),
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )

    candidate_set = PlanCandidateBuilder(context).build(resolved)
    scheduled_sessions = tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())
    activities = tuple(getattr(getattr(context, "execution", None), "activities", ()) or ())
    active_facts = tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ())
    evaluated = PlanCandidateEvaluator(db=db, user=user).evaluate(
        candidate_set,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        active_facts=active_facts,
        coach_state_bundle=coach_state_bundle,
    )
    reviewer_decision = None
    if reviewer_request_json_fn is not None:
        reviewer_decision = review_plan_patch_candidates(evaluated, request_json_fn=reviewer_request_json_fn)
    policy_decision = SportPolicy().decide(evaluated, reviewer_decision=reviewer_decision)
    selected = _selected_evaluated(policy_decision.selected_candidate_id, evaluated)
    selected_patch = getattr(selected, "patch", None) if selected is not None else None
    return PlanningDecisionResult(
        kind=policy_decision.action,
        selected_candidate_id=policy_decision.selected_candidate_id,
        candidate_options=policy_decision.candidate_options,
        reason=policy_decision.requires_confirmation_reason or policy_decision.reason,
        policy_decision=policy_decision,
        selected_patch=selected_patch,
        evaluated_candidates=tuple(evaluated),
        command_result=None,
        pending_confirmation_id=None,
    )


def _selected_evaluated(selected_candidate_id: str | None, evaluated: tuple[Any, ...]) -> Any | None:
    if selected_candidate_id is None:
        return None
    return next((candidate for candidate in evaluated if candidate.candidate.id == selected_candidate_id), None)
