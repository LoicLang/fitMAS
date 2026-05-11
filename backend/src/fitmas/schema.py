from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
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
