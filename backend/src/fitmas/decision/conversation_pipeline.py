from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas.decision import turn_calibration
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_idempotency
from fitmas.decision import turn_router
from fitmas.decision import turn_state
from fitmas.decision.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationUserNotFoundError,
)
from fitmas.decision.message_models import MessageReply
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.coaching import repo_conversation


def run_conversation_turn(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    with turn_idempotency.client_message_key_lock(user.id, payload.client_message_key):
        return _run_conversation_turn_impl(payload, db=db, dependencies=dependencies)


def _run_conversation_turn_impl(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    duplicate_reply = turn_idempotency.reply_for_duplicate_client_message(db=db, user_id=user.id, payload=payload)
    if duplicate_reply is not None:
        return duplicate_reply

    state = turn_state.load_turn_state(db=db, user=user, user_text=payload.text)
    turn_memory_writes: list[dict] = []
    pending_confirmation = repo_conversation.get_active_pending_mutation_confirmation(db, user.id)

    calibration_result = turn_calibration.apply_turn_calibration(
        db=db,
        user=user,
        payload=payload,
        state=state,
        turn_memory_writes=turn_memory_writes,
        resolve_calibration_need=dependencies.resolve_calibration_need,
    )
    open_calibration_need = calibration_result.open_calibration_need

    context_artifacts = turn_context_builder.build_turn_context_artifacts(
        db=db,
        user=user,
        payload=payload,
        state=state,
        dependencies=dependencies,
        pending_confirmation=pending_confirmation,
    )
    return turn_router.route_conversation_turn(
        db=db,
        user=user,
        payload=payload,
        dependencies=dependencies,
        state=state,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
        context_artifacts=context_artifacts,
        turn_memory_writes=turn_memory_writes,
    )
