from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.db import SessionLocal
from fitmas.memory_profile import upsert_profile_memory
from fitmas.memory_routing import split_memory_payloads


@dataclass(slots=True)
class CoachDraft:
    text: str
    proactive: bool = False
    parse_mode: str = "Markdown"
    memory_updates: list[dict] = field(default_factory=list)


def persist_draft(user_id: int, draft: CoachDraft, *, db: Session | None = None) -> s.CoachMessage:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        message = repo.add_message(
            session,
            user_id,
            "agent",
            draft.text,
            proactive=draft.proactive,
        )
        if draft.memory_updates:
            profile_payloads, working_payloads = split_memory_payloads(draft.memory_updates)
            if profile_payloads:
                upsert_profile_memory(session, user_id, profile_payloads)
            if working_payloads:
                repo.upsert_working_memory(session, user_id, working_payloads)
        return message
    finally:
        if owns_session:
            session.close()
