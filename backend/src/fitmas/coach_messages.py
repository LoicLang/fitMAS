from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.db import SessionLocal


@dataclass(slots=True)
class CoachDraft:
    text: str
    proactive: bool = False
    parse_mode: str = "Markdown"


def persist_draft(user_id: int, draft: CoachDraft, *, db: Session | None = None) -> s.CoachMessage:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        return repo.add_message(
            session,
            user_id,
            "agent",
            draft.text,
            proactive=draft.proactive,
        )
    finally:
        if owns_session:
            session.close()
