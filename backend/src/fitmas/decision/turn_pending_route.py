from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from fitmas.decision import CoachUnderstanding
from fitmas.decision.conversation_contract import (
    ConversationTurnOutcome,
    ConversationTurnState,
)
from fitmas.decision import pending_resolution
from fitmas.decision import understanding_runtime


@dataclass(slots=True)
class PendingRouteResult:
    canonical_understanding: CoachUnderstanding | None = None
    outcome: ConversationTurnOutcome | None = None


def route_pending_confirmation(
    *,
    db: Session,
    user,
    user_text: str,
    turn_plan,
    conversation_context,
    coach_bundle,
    state: ConversationTurnState,
    pending_confirmation,
    turn_context: dict[str, object],
) -> PendingRouteResult:
    if not pending_resolution.should_prepare_canonical_pending_understanding(
        pending_confirmation=pending_confirmation,
    ):
        return PendingRouteResult()

    turn_context["canonical_pending_provider"] = {
        "active_pending_id": getattr(pending_confirmation, "id", None),
        "source": "coach_understanding",
        "result": "prepared",
    }
    canonical_understanding = understanding_runtime.run_canonical_understanding_shadow(
        user=user,
        user_text=user_text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
    )
    pending_outcome = pending_resolution.apply_pending_resolution(
        db=db,
        user=user,
        decision_artifact=None,
        canonical_understanding=canonical_understanding,
        pending_confirmation=pending_confirmation,
        user_text=user_text,
        turn_plan=turn_plan,
    )
    trace = turn_context["canonical_pending_provider"]
    if pending_outcome is not None:
        trace["result"] = "handled"
        return PendingRouteResult(canonical_understanding=canonical_understanding, outcome=pending_outcome)

    trace["result"] = "no_pending_resolution" if canonical_understanding is None else "fallback_legacy"
    return PendingRouteResult(canonical_understanding=canonical_understanding)
