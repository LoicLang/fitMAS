from __future__ import annotations

from fitmas import repo_conversation
from fitmas import schema as s
from fitmas.db import Base, SessionLocal, engine, init_db


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def test_conversation_turn_idempotency_key_is_a_durable_column() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris", age=31, objective="reprendre")
        db.add(user)
        db.commit()
        db.refresh(user)

        turn = repo_conversation.add_conversation_turn(
            db,
            user_id=user.id,
            user_message="Réessaye d'échanger",
            assistant_message="Je te demande confirmation.",
            response_mode="plan_patch_confirmation",
            extraction_confidence=0.9,
            day_updated=None,
            mutation_type="plan_patch",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=1,
            decision_json="{}",
            context={"source": "telegram"},
            memory_writes=[],
            client_message_key="telegram:42:1001",
            source="telegram",
        )

        found = repo_conversation.get_conversation_turn_by_client_message_key(
            db,
            user.id,
            "telegram:42:1001",
        )

        assert found is not None
        assert found.id == turn.id
        assert found.client_message_key == "telegram:42:1001"
        assert found.source == "telegram"
    finally:
        db.close()
