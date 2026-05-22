from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.core.db import SessionLocal
from fitmas.domain.memory.profile_memory import upsert_profile_memory
from fitmas.domain.memory.routing import split_memory_payloads


@dataclass(slots=True)
class DraftPendingConfirmation:
    impact_level: str
    reason: str
    mutation_type: str
    summary: str
    source_text: str
    decision_json: str
    expires_at: datetime | None = None


@dataclass(slots=True)
class CoachDraft:
    text: str
    proactive: bool = False
    parse_mode: str = "Markdown"
    memory_updates: list[dict] = field(default_factory=list)
    pending_confirmation: DraftPendingConfirmation | None = None


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
        if draft.pending_confirmation is not None:
            pending = draft.pending_confirmation
            repo.create_pending_mutation_confirmation(
                session,
                user_id=user_id,
                impact_level=pending.impact_level,
                reason=pending.reason,
                mutation_type=pending.mutation_type,
                summary=pending.summary,
                source_text=pending.source_text or draft.text,
                decision_json=pending.decision_json,
                expires_at=pending.expires_at,
            )
        return message
    finally:
        if owns_session:
            session.close()
