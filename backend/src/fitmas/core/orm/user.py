from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    age: Mapped[int] = mapped_column(default=31)
    objective: Mapped[str] = mapped_column(Text, default="")
    coaching_style: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Paris")
    telegram_chat_id: Mapped[int | None] = mapped_column(nullable=True, default=None)
    primary_objective: Mapped[str] = mapped_column(Text, default="")
    weekly_structure_notes: Mapped[str] = mapped_column(Text, default="")
    coach_name: Mapped[str] = mapped_column(String(64), default="FitMAS")
    coach_style: Mapped[str] = mapped_column(String(32), default="direct")
    coach_relationship: Mapped[str] = mapped_column(Text, default="")
    coach_do: Mapped[str] = mapped_column(Text, default="")
    coach_dont: Mapped[str] = mapped_column(Text, default="")
    coach_soul: Mapped[str] = mapped_column(Text, default="")
    onboarding_status: Mapped[str] = mapped_column(String(32), default="not_started")

    constraints: Mapped[list[UserConstraint]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[list[UserPreference]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sports: Mapped[list[UserSport]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    facts: Mapped[list[UserFact]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    working_memory_entries: Mapped[list[WorkingMemoryEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    patterns: Mapped[list[UserPattern]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    strava_connection: Mapped[StravaConnection | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    weekly_plans: Mapped[list[WeeklyPlan]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    scheduled_sessions: Mapped[list[ScheduledSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[list[CoachMessage]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversation_turns: Mapped[list[ConversationTurnRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    fitness_snapshots: Mapped[list[FitnessSnapshotRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    readiness_snapshots: Mapped[list[ReadinessSnapshotRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    planning_decisions: Mapped[list[PlanningDecisionRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    pending_mutation_confirmations: Mapped[list[PendingMutationConfirmation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    plan_mutation_events: Mapped[list[PlanMutationEventRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memory_mutation_events: Mapped[list[MemoryMutationEventRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

class UserConstraint(Base):
    __tablename__ = "user_constraints"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="constraints")

class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="preferences")

class UserSport(Base):
    __tablename__ = "user_sports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sport_type: Mapped[str] = mapped_column(String(32))
    priority_rank: Mapped[int] = mapped_column(default=0)
    level_note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User] = relationship(back_populates="sports")
