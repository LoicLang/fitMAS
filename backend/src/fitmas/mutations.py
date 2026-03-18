from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.llm import MutationDecision

logger = logging.getLogger(__name__)


def apply(db: Session, plan_id: int, decision: MutationDecision) -> None:
    """Apply a mutation decision to the plan in DB."""

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

        logger.info("Applied move_session: %s → %s", decision.from_day, decision.to_day)

    elif decision.mutation_type == "swap_sessions":
        if not decision.from_day or not decision.to_day:
            return

        src = repo.get_day_plan(db, plan_id, decision.from_day)
        dst = repo.get_day_plan(db, plan_id, decision.to_day)
        if not src or not dst:
            return

        # Swap all session fields
        for field in ("session_title", "session_goal", "session_note", "priority", "flexibility"):
            src_val = getattr(src, field)
            dst_val = getattr(dst, field)
            setattr(src, field, dst_val)
            setattr(dst, field, src_val)

        db.commit()
        repo.set_change_notes(db, src.id, [("Seance echangee", decision.rationale)])
        repo.set_change_notes(db, dst.id, [("Seance echangee", decision.rationale)])

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

        logger.info("Applied update_session on %s: %s", decision.from_day, decision.new_title or "(goal only)")

    elif decision.mutation_type == "lighten_day":
        if not decision.from_day:
            return

        day = repo.get_day_plan(db, plan_id, decision.from_day)
        if not day:
            return

        day.session_title = "Journee flexible"
        day.session_goal = "Recuperation et disponibilite"
        day.priority = "Leger"
        day.session_note = f"Journee allegee. {decision.rationale}"
        day.flexibility = "flexible"
        db.commit()
        repo.set_change_notes(db, day.id, [("Journee allegee", decision.rationale)])

        logger.info("Applied lighten_day on %s", decision.from_day)

    # "no_change" → nothing to do
    elif decision.mutation_type == "no_change":
        logger.info("No change needed: %s", decision.rationale)
