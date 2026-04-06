from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import plan_actions, repository as repo
from fitmas.llm import MutationDecision
from fitmas.mutation_hooks import (
    PostMutationResult,
    PreMutationResult,
    run_post_mutation_hooks,
    run_pre_mutation_hooks,
)
from fitmas.time_context import get_local_now

logger = logging.getLogger(__name__)


def _resync_plan_sessions(db: Session, plan_id: int) -> None:
    plan = repo.get_plan_optional(db, plan_id)
    if plan is None or plan.user is None:
        return
    repo.resync_plan_sessions(db, plan_id, timezone_name=plan.user.timezone)


def apply(
    db: Session,
    plan_id: int,
    decision: MutationDecision,
    *,
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
    _apply_mutation(db, plan_id, decision)

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


def _apply_mutation(db: Session, plan_id: int, decision: MutationDecision) -> None:
    """Core mutation dispatch — unchanged logic, extracted from old apply()."""

    plan = repo.get_plan_optional(db, plan_id)
    user = plan.user if plan is not None else None

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
            return

        if decision.mutation_type == "lighten_day":
            session = plan_actions.lighten_session(
                db,
                user=user,
                session_id=decision.target_session_id,
                rationale=decision.rationale,
            )
            logger.info("Applied session lighten: session=%s result=%s", decision.target_session_id, session.id if session else None)
            return

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
            return

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
            return

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
            return

    if decision.mutation_type == "move_session":
        if not decision.from_day or not decision.to_day:
            return

        repo.move_session(db, plan_id, decision.from_day, decision.to_day)

        # Change notes on both days
        dst = repo.get_day_plan(db, plan_id, decision.to_day)
        if dst:
            repo.set_change_notes(db, dst.id, [("Seance deplacee ici", decision.rationale)])

        src = repo.get_day_plan(db, plan_id, decision.from_day)
        if src:
            repo.set_change_notes(db, src.id, [("Seance reportee", decision.rationale)])

        _resync_plan_sessions(db, plan_id)
        logger.info("Applied move_session: %s → %s", decision.from_day, decision.to_day)

    elif decision.mutation_type == "swap_sessions":
        if not decision.from_day or not decision.to_day:
            return

        src = repo.get_day_plan(db, plan_id, decision.from_day)
        dst = repo.get_day_plan(db, plan_id, decision.to_day)
        if not src or not dst:
            return

        # Swap all session fields
        for field in (
            "sport_type",
            "session_type",
            "session_title",
            "session_goal",
            "session_note",
            "duration_min",
            "intensity",
            "load_score",
            "priority",
            "nutrition_focus",
            "flexibility",
            "completion_status",
        ):
            src_val = getattr(src, field)
            dst_val = getattr(dst, field)
            setattr(src, field, dst_val)
            setattr(dst, field, src_val)

        db.commit()
        repo.set_change_notes(db, src.id, [("Seance echangee", decision.rationale)])
        repo.set_change_notes(db, dst.id, [("Seance echangee", decision.rationale)])

        _resync_plan_sessions(db, plan_id)
        logger.info("Applied swap_sessions: %s <-> %s", decision.from_day, decision.to_day)

    elif decision.mutation_type == "update_session":
        if not decision.from_day:
            return

        day = repo.get_day_plan(db, plan_id, decision.from_day)
        if not day:
            return

        if decision.new_title:
            day.session_title = decision.new_title
        if decision.new_goal:
            day.session_goal = decision.new_goal
        day.session_note = decision.rationale
        db.commit()
        repo.set_change_notes(db, day.id, [("Seance modifiee", decision.rationale)])

        _resync_plan_sessions(db, plan_id)
        logger.info("Applied update_session on %s: %s", decision.from_day, decision.new_title or "(goal only)")

    elif decision.mutation_type == "lighten_day":
        if not decision.from_day:
            return

        day = repo.get_day_plan(db, plan_id, decision.from_day)
        if not day:
            return

        day.sport_type = "rest"
        day.session_type = "rest"
        day.session_title = "Journee flexible"
        day.session_goal = "Recuperation et disponibilite"
        day.duration_min = None
        day.intensity = "easy"
        day.load_score = 0
        day.priority = "Leger"
        day.nutrition_focus = "Rester simple. Le but est surtout de recuperer."
        day.session_note = f"Journee allegee. {decision.rationale}"
        day.flexibility = "flexible"
        day.completion_status = "adapted"
        db.commit()
        repo.set_change_notes(db, day.id, [("Journee allegee", decision.rationale)])

        _resync_plan_sessions(db, plan_id)
        logger.info("Applied lighten_day on %s", decision.from_day)

    elif decision.mutation_type == "replace_session":
        if not decision.from_day:
            return

        day = repo.get_day_plan(db, plan_id, decision.from_day)
        if not day:
            return

        if decision.new_sport_type:
            day.sport_type = decision.new_sport_type
        if decision.new_session_type:
            day.session_type = decision.new_session_type
        if decision.new_title:
            day.session_title = decision.new_title
        if decision.new_goal:
            day.session_goal = decision.new_goal
        if decision.new_description:
            day.session_description = decision.new_description
        if decision.new_duration_min:
            day.duration_min = decision.new_duration_min
        if decision.new_intensity:
            day.intensity = decision.new_intensity
        day.session_note = decision.rationale
        day.completion_status = "adapted"
        db.commit()
        repo.set_change_notes(db, day.id, [("Seance remplacee", decision.rationale)])

        _resync_plan_sessions(db, plan_id)
        logger.info("Applied replace_session on %s: %s → %s", decision.from_day, decision.new_sport_type, decision.new_title)

    # "no_change" → nothing to do
    elif decision.mutation_type == "no_change":
        logger.info("No change needed: %s", decision.rationale)


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
