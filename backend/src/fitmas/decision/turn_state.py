from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.conversation_contract import ConversationTurnState


logger = logging.getLogger(__name__)


def load_turn_state(*, db: Session, user, user_text: str) -> ConversationTurnState:
    current_message = repo.add_message(db, user.id, "user", user_text)
    logger.info("User message: %s", user_text[:120])

    msgs = repo.get_messages(db, user.id)
    conversation_history = [{"role": msg.role, "text": msg.text} for msg in msgs]
    previous_agent_text = latest_agent_text(conversation_history[:-1])
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=21)
    timeline = [repo.to_pydantic_scheduled_session(session) for session in scheduled_sessions]
    activities = repo.get_activities(db, user.id, limit=120)
    today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    active_memory_rows, active_facts = active_memory_payloads(db, user.id)
    return ConversationTurnState(
        user=user,
        current_user_message_id=current_message.id,
        conversation_history=conversation_history,
        previous_agent_text=previous_agent_text,
        scheduled_sessions=scheduled_sessions,
        timeline=timeline,
        activities=activities,
        today_session=today_session,
        active_memory_rows=active_memory_rows,
        active_facts=active_facts,
    )


def active_memory_payloads(db: Session, user_id: int) -> tuple[list[object], list[dict]]:
    from fitmas.app.api import routes_messages as api_messages

    return api_messages._active_memory_payloads(db, user_id)


def latest_agent_text(conversation_history: list[dict]) -> str | None:
    from fitmas.app.api import routes_messages as api_messages

    return api_messages._latest_agent_text(conversation_history)
