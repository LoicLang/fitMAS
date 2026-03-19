from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.db import Base


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
    activities: Mapped[list[Activity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    strava_connection: Mapped[StravaConnection | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    weekly_plans: Mapped[list[WeeklyPlan]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[list[CoachMessage]] = relationship(
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="facts")


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    sport_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int | None] = mapped_column(nullable=True, default=None)
    distance_m: Mapped[float | None] = mapped_column(nullable=True, default=None)
    elevation_m: Mapped[float | None] = mapped_column(nullable=True, default=None)
    perceived_load: Mapped[int | None] = mapped_column(nullable=True, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    matched_day: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    match_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="activities")


class StravaConnection(Base):
    __tablename__ = "strava_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    athlete_id: Mapped[int]
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int]
    scopes: Mapped[str] = mapped_column(Text, default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="strava_connection")


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    intention: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived

    user: Mapped[User] = relationship(back_populates="weekly_plans")
    days: Mapped[list[DayPlan]] = relationship(
        back_populates="weekly_plan",
        cascade="all, delete-orphan",
        order_by="DayPlan.sort_order",
    )


class DayPlan(Base):
    __tablename__ = "day_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    weekly_plan_id: Mapped[int] = mapped_column(ForeignKey("weekly_plans.id"))
    sort_order: Mapped[int] = mapped_column(default=0)
    day: Mapped[str] = mapped_column(String(16))   # monday … sunday
    label: Mapped[str] = mapped_column(String(32))
    sport_type: Mapped[str] = mapped_column(String(32), default="running")
    session_type: Mapped[str] = mapped_column(String(32), default="easy")
    session_title: Mapped[str] = mapped_column(Text)
    session_goal: Mapped[str] = mapped_column(Text)
    session_note: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int | None] = mapped_column(nullable=True, default=None)
    intensity: Mapped[str] = mapped_column(String(16), default="easy")
    load_score: Mapped[int] = mapped_column(default=1)
    priority: Mapped[str] = mapped_column(String(32))
    nutrition_focus: Mapped[str] = mapped_column(Text)
    flexibility: Mapped[str] = mapped_column(String(16), default="stable")
    completion_status: Mapped[str] = mapped_column(String(16), default="planned")

    weekly_plan: Mapped[WeeklyPlan] = relationship(back_populates="days")
    change_notes: Mapped[list[ChangeNote]] = relationship(
        back_populates="day_plan", cascade="all, delete-orphan"
    )
    watch_items: Mapped[list[WatchItem]] = relationship(
        back_populates="day_plan", cascade="all, delete-orphan"
    )


class ChangeNote(Base):
    __tablename__ = "change_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_plan_id: Mapped[int] = mapped_column(ForeignKey("day_plans.id"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)

    day_plan: Mapped[DayPlan] = relationship(back_populates="change_notes")


class WatchItem(Base):
    __tablename__ = "watch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_plan_id: Mapped[int] = mapped_column(ForeignKey("day_plans.id"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)

    day_plan: Mapped[DayPlan] = relationship(back_populates="watch_items")


class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))   # user | agent
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="messages")
