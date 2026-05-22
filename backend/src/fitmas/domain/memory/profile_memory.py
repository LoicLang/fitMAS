from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s


def get_active_profile_memory(db: Session, user_id: int, *, limit: int = 12) -> list[s.UserFact]:
    return repo.get_active_facts(db, user_id, limit=limit)


def replace_profile_memory(db: Session, user_id: int, facts: list[dict]) -> None:
    repo.replace_user_facts(db, user_id, facts)


def upsert_profile_memory(db: Session, user_id: int, facts: list[dict]) -> list[s.UserFact]:
    return repo.upsert_facts(db, user_id, facts)
