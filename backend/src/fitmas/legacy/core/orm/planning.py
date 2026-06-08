from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.legacy.core.db import Base


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    intention: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    mesocycle_week: Mapped[int] = mapped_column(default=1)      # 1-4 dans le cycle
    mesocycle_number: Mapped[int] = mapped_column(default=1)    # n-ième cycle
    total_weeks: Mapped[int] = mapped_column(default=1)

    user: Mapped[User] = relationship(back_populates="weekly_plans")
    days: Mapped[list[DayPlan]] = relationship(
        back_populates="weekly_plan",
        cascade="all, delete-orphan",
        order_by="DayPlan.sort_order",
    )

class ScheduledSession(Base):
    __tablename__ = "scheduled_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    day: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(32))
    scheduled_date: Mapped[datetime] = mapped_column(DateTime)
    source_plan_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    sport_type: Mapped[str] = mapped_column(String(32), default="running")
    session_type: Mapped[str] = mapped_column(String(32), default="easy")
    session_title: Mapped[str] = mapped_column(Text)
    session_goal: Mapped[str] = mapped_column(Text)
    session_note: Mapped[str] = mapped_column(Text, default="")
    session_description: Mapped[str] = mapped_column(Text, default="")
    duration_min: Mapped[int | None] = mapped_column(nullable=True, default=None)
    intensity: Mapped[str] = mapped_column(String(16), default="easy")
    load_score: Mapped[int] = mapped_column(default=1)
    priority: Mapped[str] = mapped_column(String(32), default="Normal")
    nutrition_focus: Mapped[str] = mapped_column(Text, default="")
    flexibility: Mapped[str] = mapped_column(String(16), default="stable")
    completion_status: Mapped[str] = mapped_column(String(16), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="scheduled_sessions")
    activities: Mapped[list[Activity]] = relationship(back_populates="scheduled_session")

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
    session_description: Mapped[str] = mapped_column(Text, default="")
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

class PlanMutationEventRecord(Base):
    __tablename__ = "plan_mutation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(48), default="")
    trigger_type: Mapped[str] = mapped_column(String(48), default="")
    command_type: Mapped[str] = mapped_column(String(48), default="")
    target_session_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    before_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    after_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    reason_json: Mapped[str] = mapped_column(Text, default="{}")
    impact_json: Mapped[str] = mapped_column(Text, default="{}")
    user_visible_summary: Mapped[str] = mapped_column(Text, default="")
    explained_to_user: Mapped[bool] = mapped_column(Boolean, default=False)
    conversation_turn_id: Mapped[int | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="plan_mutation_events")

class PlanningDecisionRecord(Base):
    __tablename__ = "planning_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    week_start: Mapped[date] = mapped_column(Date)
    decision_version: Mapped[str] = mapped_column(String(16), default="v1")
    planning_mode: Mapped[str] = mapped_column(String(32))
    adaptation_level: Mapped[str] = mapped_column(String(16), default="none")
    adaptation_scope: Mapped[str] = mapped_column(String(16), default="week")
    weekly_target_tss: Mapped[float] = mapped_column(Float, default=0.0)
    intensity_distribution: Mapped[str] = mapped_column(String(32), default="balanced")
    key_session_count: Mapped[int] = mapped_column(default=0)
    strength_session_count: Mapped[int] = mapped_column(default=0)
    long_session: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale_json: Mapped[str] = mapped_column(Text, default="[]")
    adaptations_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="planning_decisions")
