from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.llm import MutationDecision


def apply(db: Session, plan_id: int, decision: MutationDecision) -> None:
    """Apply a mutation decision to the plan in DB."""

    if decision.mutation_type == "move_session":
        if not decision.from_day or not decision.to_day:
            return

        repo.move_session(db, plan_id, decision.from_day, decision.to_day)

        # Change notes: destination gets the rationale
        dst = repo.get_day_plan(db, plan_id, decision.to_day)
        if dst:
            repo.set_change_notes(db, dst.id, [("Seance deplacee ici", decision.rationale)])

        # Change notes: source explains what moved
        src = repo.get_day_plan(db, plan_id, decision.from_day)
        if src:
            repo.set_change_notes(db, src.id, [("Seance reportee", decision.rationale)])

    elif decision.mutation_type == "lighten_day":
        if not decision.from_day:
            return

        day = repo.get_day_plan(db, plan_id, decision.from_day)
        if not day:
            return

        day.priority = "Leger"
        day.session_note = f"Journee allegee. {decision.rationale}"
        day.flexibility = "flexible"
        db.commit()
        repo.set_change_notes(db, day.id, [("Journee allegee", decision.rationale)])

    # "no_change" → nothing to do
