from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.core.db import Base


class UserFact(Base):
    __tablename__ = "user_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="conversation")
    confidence: Mapped[float] = mapped_column(default=0.7)
    confirmed: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    urgency: Mapped[str] = mapped_column(String(16), default="medium")
    ttl: Mapped[str] = mapped_column(String(16), default="medium")
    affects_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    signal_kind: Mapped[str] = mapped_column(String(32), default="")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    resolution_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="facts")

class WorkingMemoryEntry(Base):
    __tablename__ = "working_memory_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="conversation")
    confidence: Mapped[float] = mapped_column(default=0.7)
    confirmed: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    urgency: Mapped[str] = mapped_column(String(16), default="medium")
    ttl: Mapped[str] = mapped_column(String(16), default="short")
    scope: Mapped[str] = mapped_column(String(16), default="conversation")
    affects_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    signal_kind: Mapped[str] = mapped_column(String(32), default="")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    resolution_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="working_memory_entries")

class UserPattern(Base):
    __tablename__ = "user_patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(32))
    pattern_type: Mapped[str] = mapped_column(String(48))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="maintenance")
    confidence: Mapped[float] = mapped_column(default=0.7)
    confirmed: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    urgency: Mapped[str] = mapped_column(String(16), default="medium")
    ttl: Mapped[str] = mapped_column(String(16), default="long")
    evidence_count: Mapped[int] = mapped_column(default=1)
    affects_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="patterns")

class MemoryMutationEventRecord(Base):
    __tablename__ = "memory_mutation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(48), default="conversation")
    action_type: Mapped[str] = mapped_column(String(48), default="")
    target_type: Mapped[str] = mapped_column(String(48), default="")
    target_key: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="applied")
    reason: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    conversation_turn_id: Mapped[int | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="memory_mutation_events")
