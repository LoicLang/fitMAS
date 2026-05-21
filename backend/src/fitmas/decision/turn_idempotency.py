from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Lock

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.conversation_contract import ConversationTurnInput, ConversationTurnOutcome
from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole


logger = logging.getLogger(__name__)

_CLIENT_MESSAGE_KEY_LOCKS_GUARD = Lock()
_CLIENT_MESSAGE_KEY_LOCKS: dict[str, Lock] = {}


@contextmanager
def client_message_key_lock(user_id: int, client_message_key: str | None):
    key = str(client_message_key or "").strip()
    if not key:
        yield
        return
    lock_key = f"{user_id}:{key}"
    with _CLIENT_MESSAGE_KEY_LOCKS_GUARD:
        lock = _CLIENT_MESSAGE_KEY_LOCKS.get(lock_key)
        if lock is None:
            lock = Lock()
            _CLIENT_MESSAGE_KEY_LOCKS[lock_key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def reply_for_duplicate_client_message(
    *,
    db: Session,
    user_id: int,
    payload: ConversationTurnInput,
) -> MessageReply | None:
    key = str(payload.client_message_key or "").strip()
    if not key:
        return None
    row = repo.get_conversation_turn_by_client_message_key(db, user_id, key)
    if row is None:
        return None
    logger.info("conversation_pipeline.idempotent_replay user=%s key=%s turn=%s", user_id, key, row.id)
    day_updated = _day_id_from_row(row.day_updated)
    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=row.user_message),
        extraction=Extraction(confidence=float(row.extraction_confidence or 0.0)),
        assistant_message=Message(role=MessageRole.AGENT, text=row.assistant_message),
        day_updated=day_updated,
    )


def turn_is_obsolete(*, db: Session, user, turn_context: dict[str, object]) -> bool:
    raw_message_id = turn_context.get("current_user_message_id")
    try:
        message_id = int(raw_message_id) if raw_message_id is not None else None
    except (TypeError, ValueError):
        message_id = None
    if message_id is None:
        return False
    return repo.has_newer_user_message(db, user.id, message_id)


def obsolete_turn_outcome(*, turn_context: dict[str, object]) -> ConversationTurnOutcome:
    turn_context["obsolete_turn_no_write"] = True
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=(
            "Je vois un message plus recent. "
            "Je ne touche pas au plan sur cet ancien tour."
        ),
        response_mode="obsolete_turn_no_write",
        mutation_applied=False,
    )


def _day_id_from_row(raw: str | None) -> DayId | None:
    if not raw:
        return None
    try:
        return DayId(str(raw))
    except ValueError:
        return None
