from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.core.db import Base


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    scheduled_session_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_sessions.id"), nullable=True, default=None)
    sport_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int | None] = mapped_column(nullable=True, default=None)
    distance_m: Mapped[float | None] = mapped_column(nullable=True, default=None)
    elevation_m: Mapped[float | None] = mapped_column(nullable=True, default=None)
    perceived_load: Mapped[int | None] = mapped_column(nullable=True, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    avg_hr: Mapped[float | None] = mapped_column(nullable=True, default=None)
    max_hr: Mapped[float | None] = mapped_column(nullable=True, default=None)
    avg_speed: Mapped[float | None] = mapped_column(nullable=True, default=None)
    calories: Mapped[float | None] = mapped_column(nullable=True, default=None)
    suffer_score: Mapped[int | None] = mapped_column(nullable=True, default=None)
    tss: Mapped[float | None] = mapped_column(nullable=True, default=None)
    map_polyline: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    start_latlng: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    matched_day: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    match_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="activities")
    scheduled_session: Mapped[ScheduledSession | None] = relationship(back_populates="activities")
