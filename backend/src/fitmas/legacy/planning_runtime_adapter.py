from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import Session

from fitmas.decision import CoachUnderstanding
from fitmas.domain.planning.decision_service import decide_plan_change
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.mutation_service import PlanningCommandService


@dataclass(frozen=True, slots=True)
class PlanningRuntimeAdapterAttempt:
    applicable: bool
    result: PlanningDecisionResult | None
    reason: str


def run_planning_runtime_attempt_from_understanding(
    *,
    understanding: CoachUnderstanding | None,
    context: Any,
    db: Session,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningRuntimeAdapterAttempt:
    if understanding is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="missing_understanding",
        )
    if understanding.requested_change is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="no_requested_plan_change",
        )

    planning_decision = decide_plan_change(
        understanding.requested_change,
        context=context,
        db=db,
        user=user,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if not isinstance(planning_decision, PlanningDecisionResult):
        return PlanningRuntimeAdapterAttempt(
            applicable=True,
            result=planning_decision,
            reason="non_standard_planning_result",
        )

    command_result = PlanningCommandService(db=db, user=user).apply(
        planning_decision,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        activities=tuple(getattr(getattr(context, "execution", None), "activities", ()) or ()),
        active_facts=tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ()),
    )
    return PlanningRuntimeAdapterAttempt(
        applicable=True,
        result=replace(
            planning_decision,
            command_result=command_result,
            pending_confirmation_id=command_result.pending_confirmation_id,
        ),
        reason="handled",
    )
