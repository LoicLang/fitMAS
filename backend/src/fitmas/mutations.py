from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas.domain.planning import session_actions as plan_actions
from fitmas.domain.planning.mutation_decision import MutationDecision
from fitmas.mutation_hooks import (
    PostMutationResult,
    PreMutationResult,
    run_post_mutation_hooks,
    run_pre_mutation_hooks,
)
from fitmas.time_context import get_local_now

logger = logging.getLogger(__name__)


def apply(
    db: Session,
    plan_id: int,
    decision: MutationDecision,
    *,
    user: Any | None = None,
    scheduled_sessions: Sequence[Any] = (),
    timezone_name: str | None = None,
) -> tuple[PreMutationResult, PostMutationResult | None]:
    """Apply a mutation decision to the plan in DB, with pre/post hooks.

    Returns (pre_result, post_result). post_result is None if mutation was blocked or no_change.
    """
    # --- Pre-mutation hooks ---
    pre_result = run_pre_mutation_hooks(
        db,
        plan_id,
        decision,
        scheduled_sessions=scheduled_sessions,
        timezone_name=timezone_name,
    )

    if not pre_result.allowed:
        logger.info("Mutation blocked by pre-hook: %s", pre_result.block_reason)
        return pre_result, None

    # --- Apply mutation ---
    applied = _apply_mutation(db, decision, user=user)
    if not applied:
        logger.info("Mutation produced no DB change: %s", decision.mutation_type)
        return pre_result, None

    # --- Post-mutation hooks ---
    if decision.mutation_type == "no_change":
        return pre_result, None

    post_result = run_post_mutation_hooks(
        db,
        plan_id,
        decision,
        scheduled_sessions=scheduled_sessions,
        timezone_name=timezone_name,
        pre_result=pre_result,
    )

    return pre_result, post_result


def _apply_mutation(db: Session, decision: MutationDecision, *, user: Any | None) -> bool:
    """Core mutation dispatch. Returns whether the database changed."""

    if decision.target_session_id and user is not None:
        if decision.mutation_type == "move_session":
            target_date = _resolve_target_date(decision, timezone_name=user.timezone)
            moved = plan_actions.move_session(
                db,
                user=user,
                session_id=decision.target_session_id,
                target_date=target_date,
            )
            logger.info(
                "Applied session move: session=%s target_date=%s result=%s",
                decision.target_session_id,
                target_date,
                moved.id if moved else None,
            )
            return moved is not None

        if decision.mutation_type == "lighten_day":
            session = plan_actions.lighten_session(
                db,
                user=user,
                session_id=decision.target_session_id,
                rationale=decision.rationale,
            )
            logger.info("Applied session lighten: session=%s result=%s", decision.target_session_id, session.id if session else None)
            return session is not None

        if decision.mutation_type == "swap_sessions" and decision.second_session_id:
            swapped = plan_actions.swap_sessions(
                db,
                user=user,
                first_session_id=decision.target_session_id,
                second_session_id=decision.second_session_id,
                rationale=decision.rationale,
            )
            logger.info(
                "Applied session swap: session=%s session2=%s result=%s",
                decision.target_session_id,
                decision.second_session_id,
                bool(swapped),
            )
            return bool(swapped)

        if decision.mutation_type == "update_session":
            session = plan_actions.update_session_details(
                db,
                user=user,
                session_id=decision.target_session_id,
                new_title=decision.new_title,
                new_goal=decision.new_goal,
                rationale=decision.rationale,
            )
            logger.info("Applied session update: session=%s result=%s", decision.target_session_id, session.id if session else None)
            return session is not None

        if decision.mutation_type == "replace_session":
            session = plan_actions.replace_session(
                db,
                user=user,
                session_id=decision.target_session_id,
                new_sport_type=decision.new_sport_type,
                new_session_type=decision.new_session_type,
                new_duration_min=decision.new_duration_min,
                new_intensity=decision.new_intensity,
                new_description=decision.new_description,
                new_title=decision.new_title,
                new_goal=decision.new_goal,
                rationale=decision.rationale,
            )
            logger.info("Applied session replace: session=%s result=%s", decision.target_session_id, session.id if session else None)
            return session is not None

    if decision.mutation_type in {"move_session", "swap_sessions", "update_session", "lighten_day", "replace_session"}:
        logger.info(
            "Ignored %s without runtime session target; from_day/to_day template writes are disabled.",
            decision.mutation_type,
        )
        return False

    # "no_change" → nothing to do
    if decision.mutation_type == "no_change":
        logger.info("No change needed: %s", decision.rationale)
        return False

    return False


def _resolve_target_date(decision: MutationDecision, *, timezone_name: str | None) -> date | None:
    if decision.target_date:
        try:
            return date.fromisoformat(decision.target_date)
        except ValueError:
            return None
    if decision.to_day:
        day_index = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(decision.to_day)
        today = get_local_now(timezone_name).date()
        delta = (day_index - today.weekday()) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    return None
