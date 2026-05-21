from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.decision.turn_recording import decision_json_for_turn
from fitmas.models import Extraction, Message, MessageReply, MessageRole


def persist_turn_memory_updates(
    db: Session,
    user_id: int,
    payloads: list[dict],
    *,
    turn_memory_writes: list[dict],
) -> None:
    from fitmas.app.api import routes_messages as api_messages

    if not payloads:
        return
    api_messages._persist_memory_updates(db, user_id, payloads)
    turn_memory_writes.extend(dict(payload) for payload in payloads)


def filter_legacy_extracted_facts(payloads: list[dict]) -> list[dict]:
    """Keep the legacy extractor away from availability writes.

    Availability now comes from typed LLM `memory_actions` or the typed
    `turn_plan.availability_constraint`. This function filters only legacy
    extracted fact payloads after the assistant output exists; it never reads
    or classifies user text.
    """
    return [
        payload
        for payload in payloads
        if str(payload.get("category") or "").strip().lower() != "availability"
    ]


def reply_and_record_turn(
    *,
    db: Session,
    user_id: int,
    user_text: str,
    reply_text: str,
    extraction: Extraction,
    response_mode: str,
    day_updated=None,
    decision=None,
    mutation_applied: bool = False,
    pending_confirmation: bool = False,
    pending_confirmation_id: int | None = None,
    turn_context: dict[str, object] | None = None,
    memory_writes: list[dict] | None = None,
) -> MessageReply:
    repo.add_message(db, user_id, "agent", reply_text)
    repo.add_conversation_turn(
        db,
        user_id=user_id,
        user_message=user_text,
        assistant_message=reply_text,
        response_mode=response_mode,
        extraction_confidence=float(extraction.confidence or 0.0),
        day_updated=getattr(day_updated, "value", day_updated),
        mutation_type=str(getattr(decision, "mutation_type", "") or ""),
        mutation_applied=mutation_applied,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=pending_confirmation_id,
        decision_json=decision_json_for_turn(decision),
        context=turn_context,
        memory_writes=memory_writes,
        client_message_key=str((turn_context or {}).get("client_message_key") or "").strip() or None,
        source=str((turn_context or {}).get("source") or "").strip() or None,
    )
    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=user_text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
        day_updated=day_updated,
    )
