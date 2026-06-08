from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fitmas.legacy.core.db import Base


class FitnessSnapshotRecord(Base):
    __tablename__ = "fitness_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    ctl: Mapped[float] = mapped_column(Float, default=0.0)
    atl: Mapped[float] = mapped_column(Float, default=0.0)
    tsb: Mapped[float] = mapped_column(Float, default=0.0)
    ramp_rate: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_target_tss: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_actual_tss: Mapped[float] = mapped_column(Float, default=0.0)
    completion_rate_14d: Mapped[float] = mapped_column(Float, default=0.0)
    key_sessions_done_14d: Mapped[int] = mapped_column(default=0)
    volume_sessions_done_14d: Mapped[int] = mapped_column(default=0)
    sport_ctl_json: Mapped[str] = mapped_column(Text, default="{}")
    sport_volume_hours_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="fitness_snapshots")

class ReadinessSnapshotRecord(Base):
    __tablename__ = "readiness_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    physical: Mapped[str] = mapped_column(String(16))
    mental: Mapped[str] = mapped_column(String(16))
    logistical: Mapped[str] = mapped_column(String(16))
    injury_risk: Mapped[str] = mapped_column(String(16))
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="readiness_snapshots")
