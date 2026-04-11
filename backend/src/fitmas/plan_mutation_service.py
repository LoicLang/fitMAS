from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo, schema as s
from fitmas.llm import MutationDecision


@dataclass(frozen=True, slots=True)
class PlanMutationServiceResult:
    plan_id: int
    applied_count: int
    attempted_count: int


def apply_decisions_for_user(
    db: Session,
    *,
    user: s.User,
    decisions: Sequence[MutationDecision],
) -> PlanMutationServiceResult | None:
    if not decisions:
        return None

    plan = repo.get_active_plan(db, user.id)
    applied_count = 0
    for decision in decisions:
        pre_result, post_result = mutations.apply(
            db,
            plan.id,
            decision,
        )
        if pre_result.allowed and post_result is not None:
            applied_count += 1

    return PlanMutationServiceResult(
        plan_id=plan.id,
        applied_count=applied_count,
        attempted_count=len(decisions),
    )
