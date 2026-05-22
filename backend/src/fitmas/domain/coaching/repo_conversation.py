from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from fitmas import schema as s

logger = logging.getLogger(__name__)


def get_messages(db: Session, user_id: int) -> list[s.CoachMessage]:
    return (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user_id)
        .order_by(s.CoachMessage.id)
        .all()
    )


def has_newer_user_message(db: Session, user_id: int, message_id: int | None) -> bool:
    if message_id is None:
        return False
    return (
        db.query(s.CoachMessage.id)
        .filter(
            s.CoachMessage.user_id == user_id,
            s.CoachMessage.role == "user",
            s.CoachMessage.id > int(message_id),
        )
        .order_by(s.CoachMessage.id.asc())
        .first()
        is not None
    )


def get_recent_conversation_turns(
    db: Session,
    user_id: int,
    *,
    limit: int = 20,
) -> list[s.ConversationTurnRecord]:
    return (
        db.query(s.ConversationTurnRecord)
        .filter(s.ConversationTurnRecord.user_id == user_id)
        .order_by(s.ConversationTurnRecord.id.desc())
        .limit(limit)
        .all()
    )


def get_conversation_turn_by_client_message_key(
    db: Session,
    user_id: int,
    client_message_key: str,
    *,
    limit: int = 50,
) -> s.ConversationTurnRecord | None:
    """Return a recent turn for an external delivery idempotency key."""
    key = str(client_message_key or "").strip()
    if not key:
        return None
    row = (
        db.query(s.ConversationTurnRecord)
        .filter(
            s.ConversationTurnRecord.user_id == user_id,
            s.ConversationTurnRecord.client_message_key == key,
        )
        .order_by(s.ConversationTurnRecord.id.desc())
        .first()
    )
    if row is not None:
        return row
    rows = get_recent_conversation_turns(db, user_id, limit=limit)
    for row in rows:
        try:
            context = json.loads(row.context_json or "{}")
        except Exception:
            continue
        if isinstance(context, dict) and str(context.get("client_message_key") or "").strip() == key:
            return row
    return None


def get_active_pending_mutation_confirmation(
    db: Session, user_id: int
) -> s.PendingMutationConfirmation | None:
    now = _utc_now()
    expired_rows = (
        db.query(s.PendingMutationConfirmation)
        .filter(
            s.PendingMutationConfirmation.user_id == user_id,
            s.PendingMutationConfirmation.status == "pending",
            s.PendingMutationConfirmation.expires_at.is_not(None),
            s.PendingMutationConfirmation.expires_at <= now,
        )
        .all()
    )
    if expired_rows:
        for row in expired_rows:
            row.status = "expired"
            row.resolved_at = now
        db.commit()

    rows = (
        db.query(s.PendingMutationConfirmation)
        .filter(
            s.PendingMutationConfirmation.user_id == user_id,
            s.PendingMutationConfirmation.status == "pending",
        )
        .order_by(
            s.PendingMutationConfirmation.created_at.desc(),
            s.PendingMutationConfirmation.id.desc(),
        )
        .limit(2)
        .all()
    )
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "pending_confirmation_ambiguous user=%s active_count_at_least=%s latest_ids=%s",
            user_id,
            len(rows),
            [row.id for row in rows],
        )
        return None
    return rows[0]


def add_message(
    db: Session,
    user_id: int,
    role: str,
    text: str,
    *,
    proactive: bool = False,
) -> s.CoachMessage:
    msg = s.CoachMessage(user_id=user_id, role=role, text=text, proactive=proactive)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def add_conversation_turn(
    db: Session,
    *,
    user_id: int,
    user_message: str,
    assistant_message: str,
    response_mode: str,
    extraction_confidence: float,
    day_updated: str | None,
    mutation_type: str,
    mutation_applied: bool,
    pending_confirmation: bool,
    pending_confirmation_id: int | None,
    decision_json: str,
    context: dict[str, object] | None,
    memory_writes: list[dict[str, object]] | None,
    client_message_key: str | None = None,
    source: str | None = None,
) -> s.ConversationTurnRecord:
    row = s.ConversationTurnRecord(
        user_id=user_id,
        user_message=user_message,
        assistant_message=assistant_message,
        response_mode=response_mode,
        extraction_confidence=extraction_confidence,
        day_updated=day_updated,
        mutation_type=mutation_type,
        mutation_applied=mutation_applied,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=pending_confirmation_id,
        client_message_key=str(client_message_key or "").strip() or None,
        source=str(source or "").strip() or None,
        decision_json=decision_json,
        context_json=_json_dumps(context or {}),
        memory_writes_json=_json_dumps(memory_writes or []),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_pending_mutation_confirmation(
    db: Session,
    *,
    user_id: int,
    impact_level: str,
    reason: str,
    mutation_type: str,
    summary: str,
    source_text: str,
    decision_json: str,
    expires_at: datetime | None,
) -> s.PendingMutationConfirmation:
    (
        db.query(s.PendingMutationConfirmation)
        .filter(
            s.PendingMutationConfirmation.user_id == user_id,
            s.PendingMutationConfirmation.status == "pending",
        )
        .update(
            {
                s.PendingMutationConfirmation.status: "superseded",
                s.PendingMutationConfirmation.resolved_at: _utc_now(),
            },
            synchronize_session=False,
        )
    )
    row = s.PendingMutationConfirmation(
        user_id=user_id,
        impact_level=impact_level,
        reason=reason,
        mutation_type=mutation_type,
        summary=summary,
        source_text=source_text,
        decision_json=decision_json,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_pending_mutation_confirmation(
    db: Session,
    row_id: int,
    *,
    status: str,
) -> s.PendingMutationConfirmation | None:
    row = (
        db.query(s.PendingMutationConfirmation)
        .filter(s.PendingMutationConfirmation.id == row_id)
        .first()
    )
    if row is None:
        return None
    row.status = status
    row.resolved_at = _utc_now()
    db.commit()
    db.refresh(row)
    return row


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
