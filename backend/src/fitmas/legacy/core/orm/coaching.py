from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.legacy.core.db import Base


class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))   # user | agent
    text: Mapped[str] = mapped_column(Text)
    proactive: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="messages")

class ConversationTurnRecord(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    response_mode: Mapped[str] = mapped_column(String(32), default="reply")
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    day_updated: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    mutation_type: Mapped[str] = mapped_column(String(32), default="")
    mutation_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_confirmation_id: Mapped[int | None] = mapped_column(nullable=True, default=None)
    client_message_key: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    decision_json: Mapped[str] = mapped_column(Text, default="{}")
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    memory_writes_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="conversation_turns")

class PendingMutationConfirmation(Base):
    __tablename__ = "pending_mutation_confirmations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    impact_level: Mapped[str] = mapped_column(String(16), default="high")
    reason: Mapped[str] = mapped_column(String(64), default="")
    mutation_type: Mapped[str] = mapped_column(String(32), default="no_change")
    summary: Mapped[str] = mapped_column(Text, default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    decision_json: Mapped[str] = mapped_column(Text, default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    user: Mapped[User] = relationship(back_populates="pending_mutation_confirmations")

class AdaptationEventRecord(Base):
    __tablename__ = "adaptation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason_code: Mapped[str] = mapped_column(String(48), default="logistics_conflict")
    adaptation_level: Mapped[str] = mapped_column(String(16), default="micro")
    week_mission_status: Mapped[str] = mapped_column(String(16), default="unchanged")
    trajectory_impact: Mapped[str] = mapped_column(String(16), default="low")
    scenario_type: Mapped[str] = mapped_column(String(32), default="move")
    mutation_type: Mapped[str] = mapped_column(String(32), default="no_change")
    summary: Mapped[str] = mapped_column(Text, default="")
    what_changed: Mapped[str] = mapped_column(Text, default="")
    what_protected: Mapped[str] = mapped_column(Text, default="")
    user_message: Mapped[str] = mapped_column(Text, default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    change_cost: Mapped[int] = mapped_column(default=0)
    stability_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    protected_session_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
