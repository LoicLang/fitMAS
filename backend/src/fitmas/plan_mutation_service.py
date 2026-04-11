from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import mutations, plan_actions, repository as repo, schema as s
from fitmas.llm import MutationDecision


@dataclass(frozen=True, slots=True)
class PlanMutationServiceResult:
    plan_id: int
    applied_count: int
    attempted_count: int


@dataclass(frozen=True, slots=True)
class PlanSessionActionResult:
    action_type: str
    source: str
    session: s.ScheduledSession


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


def complete_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    return PlanSessionActionResult(action_type="complete_session", source=source, session=session)


def skip_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    session = plan_actions.skip_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    return PlanSessionActionResult(action_type="skip_session", source=source, session=session)


def move_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    target_date: date | None,
    source: str,
) -> PlanSessionActionResult | None:
    session = plan_actions.move_session(db, user=user, session_id=session_id, target_date=target_date)
    if session is None:
        return None
    return PlanSessionActionResult(action_type="move_session", source=source, session=session)


def mark_session_completed_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int | None,
    source: str,
) -> PlanSessionActionResult | None:
    if session_id is None:
        return None
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    return PlanSessionActionResult(action_type="activity_completed", source=source, session=session)


def mark_day_completed_for_user(
    db: Session,
    *,
    plan_id: int,
    day: str,
    source: str,
) -> bool:
    return repo.mark_day_completed(db, plan_id, day)
