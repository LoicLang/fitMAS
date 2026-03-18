from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    age: Mapped[int]
    objective: Mapped[str] = mapped_column(Text)
    coaching_style: Mapped[str] = mapped_column(Text)

    constraints: Mapped[list[UserConstraint]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[list[UserPreference]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
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
    session_title: Mapped[str] = mapped_column(Text)
    session_goal: Mapped[str] = mapped_column(Text)
    session_note: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(32))
    nutrition_focus: Mapped[str] = mapped_column(Text)
    flexibility: Mapped[str] = mapped_column(String(16), default="stable")

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
