from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from fitmas import repo_conversation, schema as s
from fitmas.adaptation_log import AdaptationLogEntry
from fitmas.fact_memory import fact_is_current, normalize_fact_payload
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.models import (
    Activity,
    ChangeNote,
    DayId,
    DayPlan,
    Message,
    MessageRole,
    Profile,
    ScheduledSession,
    UserFact,
    UserPattern,
    WatchItem,
    WeeklyPlan,
)
from fitmas.planning_decision import PlanningDecision
from fitmas.periodization import compute_mesocycle_state, derive_total_weeks
from fitmas.readiness import ReadinessState
from fitmas.session_metadata import compute_load_band
from fitmas.time_context import DAY_KEYS, current_week_dates, get_local_now
from fitmas.week_metadata import build_week_label


# ── Converters ─────────────────────────────────────────────────────────────

def to_pydantic_profile(user: s.User) -> Profile:
    return Profile(
        name=user.name,
        age=user.age,
        objective=user.primary_objective or user.objective,
        coaching_style=user.coach_soul or user.coaching_style,
        primary_objective=user.primary_objective,
        weekly_structure_notes=user.weekly_structure_notes,
        coach_name=user.coach_name,
        coach_style=user.coach_style,
        coach_relationship=user.coach_relationship,
        coach_do=user.coach_do,
        coach_dont=user.coach_dont,
        coach_soul=user.coach_soul,
        onboarding_status=user.onboarding_status,
        sports=[sport.sport_type for sport in user.sports if sport.active],
        constraints=[c.text for c in user.constraints],
        preferences=[p.text for p in user.preferences],
        integrations=["Strava", "Telegram", "Manual"],
    )


def to_pydantic_day(day: s.DayPlan) -> DayPlan:
    load_band = compute_load_band(
        sport_type=day.sport_type,
        session_type=day.session_type,
        intensity=day.intensity,
        load_score=day.load_score,
    )
    return DayPlan(
        day=DayId(day.day),
        label=day.label,
        sport_type=day.sport_type,
        session_type=day.session_type,
        session_title=day.session_title,
        session_goal=day.session_goal,
        session_note=day.session_note,
        session_description=day.session_description or "",
        duration_min=day.duration_min,
        intensity=day.intensity,
        load_score=day.load_score,
        load_band=load_band,
        priority=day.priority,
        nutrition_focus=day.nutrition_focus,
        flexibility=day.flexibility,
        completion_status=day.completion_status,
        change_notes=[ChangeNote(title=n.title, detail=n.detail) for n in day.change_notes],
        watch_items=[WatchItem(title=w.title, detail=w.detail) for w in day.watch_items],
    )


def to_pydantic_plan(plan: s.WeeklyPlan) -> WeeklyPlan:
    total_weeks = int(getattr(plan, "total_weeks", 0) or 0)
    if total_weeks < 1:
        total_weeks = derive_total_weeks(
            mesocycle_number=getattr(plan, "mesocycle_number", 1),
            mesocycle_week=getattr(plan, "mesocycle_week", 1),
        )
    mesocycle = compute_mesocycle_state(total_weeks=total_weeks)
    return WeeklyPlan(
        intention=plan.intention,
        summary=plan.summary,
        mesocycle_week=mesocycle.week_in_cycle,
        mesocycle_number=mesocycle.cycle_number,
        cycle_length=mesocycle.cycle_length,
        total_weeks=mesocycle.total_weeks,
        is_deload=mesocycle.is_recovery_week,
        week_label=build_week_label(mesocycle),
        days=[to_pydantic_day(d) for d in plan.days],
    )


def to_pydantic_message(msg: s.CoachMessage) -> Message:
    return Message(role=MessageRole(msg.role), text=msg.text)


def to_domain_adaptation_event(record: s.AdaptationEventRecord) -> AdaptationLogEntry:
    from fitmas.adaptation_decision import DecisionReasonCode, TrajectoryImpact, WeekMissionStatus
    from fitmas.adaptation_log import _impact_label, _mission_label, _reason_label

    reason_code = DecisionReasonCode(str(record.reason_code or DecisionReasonCode.LOGISTICS_CONFLICT.value))
    week_mission_status = WeekMissionStatus(str(record.week_mission_status or WeekMissionStatus.UNCHANGED.value))
    trajectory_impact = TrajectoryImpact(str(record.trajectory_impact or TrajectoryImpact.LOW.value))
    return AdaptationLogEntry(
        created_at=record.created_at.isoformat() if record.created_at else None,
        reason_code=record.reason_code,
        reason_label=_reason_label(reason_code),
        adaptation_level=record.adaptation_level,
        week_mission_status=record.week_mission_status,
        mission_label=_mission_label(week_mission_status),
        trajectory_impact=record.trajectory_impact,
        impact_label=_impact_label(trajectory_impact),
        scenario_type=record.scenario_type,
        mutation_type=record.mutation_type,
        summary=record.summary,
        what_changed=record.what_changed,
        what_protected=record.what_protected,
        user_message=record.user_message,
        source_text=record.source_text,
        change_cost=int(record.change_cost or 0),
        stability_penalty=float(record.stability_penalty or 0.0),
        protected_session_ids=tuple(int(value) for value in _json_loads_list(record.protected_session_ids_json)),
    )


def to_pydantic_scheduled_session(session: s.ScheduledSession) -> ScheduledSession:
    linked_activity_id = None
    if session.activities:
        linked_activity_id = max((activity.id for activity in session.activities), default=None)
    load_band = compute_load_band(
        sport_type=session.sport_type,
        session_type=session.session_type,
        intensity=session.intensity,
        load_score=session.load_score,
    )
    return ScheduledSession(
        id=session.id,
        day=DayId(session.day),
        label=session.label,
        scheduled_date=session.scheduled_date.date().isoformat(),
        sport_type=session.sport_type,
        session_type=session.session_type,
        session_title=session.session_title,
        session_goal=session.session_goal,
        session_note=session.session_note or "",
        session_description=session.session_description or "",
        duration_min=session.duration_min,
        intensity=session.intensity,
        load_score=session.load_score,
        load_band=load_band,
        priority=session.priority,
        nutrition_focus=session.nutrition_focus or "",
        flexibility=session.flexibility,
        completion_status=session.completion_status,
        linked_activity_id=linked_activity_id,
    )


def to_pydantic_fact(fact: object) -> UserFact:
    return UserFact(
        category=str(getattr(fact, "category", "")),
        key=str(getattr(fact, "key", "")),
        value=str(getattr(fact, "value", "")),
        source=str(getattr(fact, "source", "conversation")),
        confidence=float(getattr(fact, "confidence", 0.0) or 0.0),
        confirmed=bool(getattr(fact, "confirmed", False)),
        active=bool(getattr(fact, "active", True)),
        urgency=str(getattr(fact, "urgency", "medium")),
        ttl=str(getattr(fact, "ttl", "medium")),
        affects=_json_loads_list(str(getattr(fact, "affects_json", "[]") or "[]")),
        expires_at=getattr(fact, "expires_at", None).isoformat() if getattr(fact, "expires_at", None) else None,
    )


def to_pydantic_pattern(pattern: s.UserPattern) -> UserPattern:
    return UserPattern(
        category=pattern.category,
        pattern_type=pattern.pattern_type,
        key=pattern.key,
        value=pattern.value,
        source=pattern.source,
        confidence=float(pattern.confidence or 0.0),
        confirmed=bool(pattern.confirmed),
        active=bool(pattern.active),
        urgency=pattern.urgency,
        ttl=pattern.ttl,
        evidence_count=int(pattern.evidence_count or 0),
        affects=_json_loads_list(pattern.affects_json),
        first_seen_at=pattern.first_seen_at.isoformat() if pattern.first_seen_at else None,
        last_seen_at=pattern.last_seen_at.isoformat() if pattern.last_seen_at else None,
    )


def to_pydantic_activity(activity: s.Activity) -> Activity:
    return Activity(
        id=activity.id,
        source=activity.source,
        external_id=activity.external_id,
        scheduled_session_id=activity.scheduled_session_id,
        sport_type=activity.sport_type,
        title=activity.title,
        duration_min=activity.duration_min,
        distance_m=activity.distance_m,
        elevation_m=activity.elevation_m,
        perceived_load=activity.perceived_load,
        note=activity.note,
        started_at=activity.started_at.isoformat() if activity.started_at else None,
        matched_day=activity.matched_day,
        match_reason=activity.match_reason,
        avg_hr=activity.avg_hr,
        max_hr=activity.max_hr,
        avg_speed=activity.avg_speed,
        calories=activity.calories,
        suffer_score=activity.suffer_score,
        tss=activity.tss,
        map_polyline=activity.map_polyline,
        start_latlng=activity.start_latlng,
    )


def to_domain_fitness_snapshot(row: s.FitnessSnapshotRecord) -> FitnessSnapshot:
    return FitnessSnapshot(
        user_id=row.user_id,
        date=row.snapshot_date,
        ctl=row.ctl,
        atl=row.atl,
        tsb=row.tsb,
        ramp_rate=row.ramp_rate,
        weekly_target_tss=row.weekly_target_tss,
        weekly_actual_tss=row.weekly_actual_tss,
        completion_rate_14d=row.completion_rate_14d,
        key_sessions_done_14d=row.key_sessions_done_14d,
        volume_sessions_done_14d=row.volume_sessions_done_14d,
        sport_ctl=_json_loads_dict(row.sport_ctl_json),
        sport_volume_hours=_json_loads_dict(row.sport_volume_hours_json),
    )


def to_domain_readiness_snapshot(row: s.ReadinessSnapshotRecord) -> ReadinessState:
    return ReadinessState(
        user_id=row.user_id,
        date=row.snapshot_date,
        physical=row.physical,
        mental=row.mental,
        logistical=row.logistical,
        injury_risk=row.injury_risk,
        risk_flags=tuple(_json_loads_list(row.risk_flags_json)),
        summary=row.summary,
    )


def to_domain_planning_decision(row: s.PlanningDecisionRecord) -> PlanningDecision:
    return PlanningDecision(
        user_id=row.user_id,
        week_start=row.week_start,
        decision_version=row.decision_version,
        planning_mode=row.planning_mode,
        adaptation_level=row.adaptation_level,
        adaptation_scope=row.adaptation_scope,
        weekly_target_tss=row.weekly_target_tss,
        intensity_distribution=row.intensity_distribution,
        key_session_count=row.key_session_count,
        strength_session_count=row.strength_session_count,
        long_session=row.long_session,
        rationale=tuple(_json_loads_list(row.rationale_json)),
        adaptations=tuple(_json_loads_list(row.adaptations_json)),
        risk_flags=tuple(_json_loads_list(row.risk_flags_json)),
    )


# ── Queries ────────────────────────────────────────────────────────────────

def get_user(db: Session) -> s.User:
    user = get_user_optional(db)
    if user is None:
        raise RuntimeError("No user in DB — onboarding required")
    return user


def get_user_optional(db: Session) -> s.User | None:
    user = db.query(s.User).first()
    return user


def get_active_plan_optional(db: Session, user_id: int) -> s.WeeklyPlan | None:
    return (
        db.query(s.WeeklyPlan)
        .filter(s.WeeklyPlan.user_id == user_id, s.WeeklyPlan.status == "active")
        .first()
    )


def get_active_plan(db: Session, user_id: int) -> s.WeeklyPlan:
    plan = get_active_plan_optional(db, user_id)
    if plan is None:
        raise RuntimeError("No active plan in DB")
    return plan


def get_plan_optional(db: Session, plan_id: int) -> s.WeeklyPlan | None:
    return db.query(s.WeeklyPlan).filter(s.WeeklyPlan.id == plan_id).first()


def get_day_plan(db: Session, plan_id: int, day: str) -> s.DayPlan | None:
    return (
        db.query(s.DayPlan)
        .filter(s.DayPlan.weekly_plan_id == plan_id, s.DayPlan.day == day)
        .first()
    )


def get_messages(db: Session, user_id: int) -> list[s.CoachMessage]:
    return repo_conversation.get_messages(db, user_id)


def get_recent_conversation_turns(
    db: Session,
    user_id: int,
    *,
    limit: int = 20,
) -> list[s.ConversationTurnRecord]:
    return repo_conversation.get_recent_conversation_turns(db, user_id, limit=limit)


def get_conversation_turn_by_client_message_key(
    db: Session,
    user_id: int,
    client_message_key: str,
    *,
    limit: int = 50,
) -> s.ConversationTurnRecord | None:
    return repo_conversation.get_conversation_turn_by_client_message_key(
        db,
        user_id,
        client_message_key,
        limit=limit,
    )


def get_active_pending_mutation_confirmation(
    db: Session, user_id: int
) -> s.PendingMutationConfirmation | None:
    return repo_conversation.get_active_pending_mutation_confirmation(db, user_id)


def get_active_facts(db: Session, user_id: int, limit: int = 12) -> list[s.UserFact]:
    rows = (
        db.query(s.UserFact)
        .filter(s.UserFact.user_id == user_id, s.UserFact.active.is_(True))
        .order_by(s.UserFact.confirmed.desc(), s.UserFact.confidence.desc(), s.UserFact.updated_at.desc())
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_working_memory(db: Session, user_id: int, limit: int = 12) -> list[s.WorkingMemoryEntry]:
    rows = (
        db.query(s.WorkingMemoryEntry)
        .filter(s.WorkingMemoryEntry.user_id == user_id, s.WorkingMemoryEntry.active.is_(True))
        .order_by(s.WorkingMemoryEntry.confirmed.desc(), s.WorkingMemoryEntry.confidence.desc(), s.WorkingMemoryEntry.updated_at.desc())
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_patterns(db: Session, user_id: int, limit: int = 6) -> list[s.UserPattern]:
    rows = (
        db.query(s.UserPattern)
        .filter(s.UserPattern.user_id == user_id, s.UserPattern.active.is_(True))
        .order_by(
            s.UserPattern.confirmed.desc(),
            s.UserPattern.confidence.desc(),
            s.UserPattern.evidence_count.desc(),
            s.UserPattern.updated_at.desc(),
        )
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_memory_items(
    db: Session,
    user_id: int,
    *,
    profile_limit: int = 12,
    working_limit: int = 12,
    include_patterns: bool = False,
    pattern_limit: int = 6,
    total_limit: int = 24,
) -> list[object]:
    items = [
        *get_active_facts(db, user_id, limit=profile_limit),
        *get_active_working_memory(db, user_id, limit=working_limit),
    ]
    if include_patterns:
        items.extend(get_active_patterns(db, user_id, limit=pattern_limit))
    items.sort(
        key=lambda row: (
            bool(getattr(row, "confirmed", False)),
            float(getattr(row, "confidence", 0.0) or 0.0),
            float(getattr(row, "evidence_count", 0) or 0),
            getattr(row, "updated_at", None) or getattr(row, "created_at", None),
        ),
        reverse=True,
    )
    return items[:total_limit]


def get_latest_fitness_snapshot_record(db: Session, user_id: int) -> s.FitnessSnapshotRecord | None:
    return (
        db.query(s.FitnessSnapshotRecord)
        .filter(s.FitnessSnapshotRecord.user_id == user_id)
        .order_by(s.FitnessSnapshotRecord.snapshot_date.desc(), s.FitnessSnapshotRecord.id.desc())
        .first()
    )


def get_latest_readiness_snapshot_record(db: Session, user_id: int) -> s.ReadinessSnapshotRecord | None:
    return (
        db.query(s.ReadinessSnapshotRecord)
        .filter(s.ReadinessSnapshotRecord.user_id == user_id)
        .order_by(s.ReadinessSnapshotRecord.snapshot_date.desc(), s.ReadinessSnapshotRecord.id.desc())
        .first()
    )


def get_latest_planning_decision_record(db: Session, user_id: int) -> s.PlanningDecisionRecord | None:
    return (
        db.query(s.PlanningDecisionRecord)
        .filter(s.PlanningDecisionRecord.user_id == user_id)
        .order_by(s.PlanningDecisionRecord.week_start.desc(), s.PlanningDecisionRecord.id.desc())
        .first()
    )


def get_activities(db: Session, user_id: int, limit: int = 30) -> list[s.Activity]:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id)
        .order_by(s.Activity.started_at.is_(None), s.Activity.started_at.desc(), s.Activity.created_at.desc())
        .limit(limit)
        .all()
    )


def get_recent_activity_for_sport(
    db: Session,
    user_id: int,
    *,
    sport_type: str,
    before: datetime | None = None,
) -> s.Activity | None:
    query = (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id, s.Activity.sport_type == sport_type)
    )
    if before is not None:
        query = query.filter(s.Activity.started_at.is_not(None), s.Activity.started_at < before)
    return (
        query
        .order_by(s.Activity.started_at.is_(None), s.Activity.started_at.desc(), s.Activity.created_at.desc())
        .first()
    )


def get_activity_by_external_id(db: Session, user_id: int, external_id: str) -> s.Activity | None:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id, s.Activity.external_id == external_id)
        .first()
    )


def get_strava_connection(db: Session, user_id: int) -> s.StravaConnection | None:
    return (
        db.query(s.StravaConnection)
        .filter(s.StravaConnection.user_id == user_id)
        .first()
    )


def get_scheduled_sessions(
    db: Session,
    user_id: int,
    *,
    date_from: date | None = None,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    query = db.query(s.ScheduledSession).filter(s.ScheduledSession.user_id == user_id)
    if date_from is not None:
        return (
            query
            .filter(s.ScheduledSession.scheduled_date >= datetime.combine(date_from, time.min))
            .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
            .limit(limit)
            .all()
        )
    sessions = (
        query
        .order_by(s.ScheduledSession.scheduled_date.desc(), s.ScheduledSession.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(sessions))


def get_scheduled_sessions_for_date(
    db: Session,
    user_id: int,
    *,
    target_date: date,
) -> list[s.ScheduledSession]:
    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
        .all()
    )


def get_scheduled_sessions_between_dates(
    db: Session,
    user_id: int,
    *,
    start_date: date,
    end_date: date,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date + timedelta(days=1), time.min)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.scheduled_date.asc(), s.ScheduledSession.id.asc())
        .limit(limit)
        .all()
    )


def get_scheduled_session_for_date(
    db: Session,
    user_id: int,
    *,
    day: str,
    scheduled_date: datetime,
) -> s.ScheduledSession | None:
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.day == day,
            s.ScheduledSession.scheduled_date == scheduled_date,
        )
        .first()
    )


def get_scheduled_session(db: Session, user_id: int, session_id: int) -> s.ScheduledSession | None:
    return (
        db.query(s.ScheduledSession)
        .filter(s.ScheduledSession.user_id == user_id, s.ScheduledSession.id == session_id)
        .first()
    )


def get_today_scheduled_session(
    db: Session,
    user_id: int,
    *,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    local_date = get_local_now(timezone_name).date()
    day_start = datetime.combine(local_date, time.min)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.id.asc())
        .first()
    )


def find_scheduled_session_for_activity(
    db: Session,
    *,
    user_id: int,
    sport_type: str,
    started_at: datetime | None,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    if started_at is None:
        local_date = get_local_now(timezone_name).date()
    elif started_at.tzinfo is None:
        local_date = started_at.date()
    else:
        local_date = get_local_now(timezone_name, now=started_at).date()

    day_start = datetime.combine(local_date, time.min)
    day_end = day_start + timedelta(days=1)
    sessions = (
        db.query(s.ScheduledSession)
        .filter(
            s.ScheduledSession.user_id == user_id,
            s.ScheduledSession.scheduled_date >= day_start,
            s.ScheduledSession.scheduled_date < day_end,
        )
        .order_by(s.ScheduledSession.id.asc())
        .all()
    )
    if not sessions:
        return None

    for session in sessions:
        if session.sport_type == sport_type and session.completion_status != "done":
            return session
    return None


# ── Writes ─────────────────────────────────────────────────────────────────

def add_message(
    db: Session,
    user_id: int,
    role: str,
    text: str,
    *,
    proactive: bool = False,
) -> s.CoachMessage:
    return repo_conversation.add_message(db, user_id, role, text, proactive=proactive)


def add_conversation_turn(
    db: Session,
    *,
    user_id: int,
    user_message: str,
    assistant_message: str,
    response_mode: str,
    extraction_confidence: float,
    day_updated: str | None,
    mutation_type: str,
    mutation_applied: bool,
    pending_confirmation: bool,
    pending_confirmation_id: int | None,
    decision_json: str,
    context: dict[str, object] | None,
    memory_writes: list[dict[str, object]] | None,
    client_message_key: str | None = None,
    source: str | None = None,
) -> s.ConversationTurnRecord:
    return repo_conversation.add_conversation_turn(
        db,
        user_id=user_id,
        user_message=user_message,
        assistant_message=assistant_message,
        response_mode=response_mode,
        extraction_confidence=extraction_confidence,
        day_updated=day_updated,
        mutation_type=mutation_type,
        mutation_applied=mutation_applied,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=pending_confirmation_id,
        decision_json=decision_json,
        context=context,
        memory_writes=memory_writes,
        client_message_key=client_message_key,
        source=source,
    )


def create_pending_mutation_confirmation(
    db: Session,
    *,
    user_id: int,
    impact_level: str,
    reason: str,
    mutation_type: str,
    summary: str,
    source_text: str,
    decision_json: str,
    expires_at: datetime | None,
) -> s.PendingMutationConfirmation:
    return repo_conversation.create_pending_mutation_confirmation(
        db,
        user_id=user_id,
        impact_level=impact_level,
        reason=reason,
        mutation_type=mutation_type,
        summary=summary,
        source_text=source_text,
        decision_json=decision_json,
        expires_at=expires_at,
    )


def resolve_pending_mutation_confirmation(
    db: Session,
    row_id: int,
    *,
    status: str,
) -> s.PendingMutationConfirmation | None:
    return repo_conversation.resolve_pending_mutation_confirmation(db, row_id, status=status)


def add_plan_mutation_event(
    db: Session,
    *,
    user_id: int,
    source: str,
    trigger_type: str,
    command_type: str,
    target_session_ids: list[int],
    before_snapshot: dict | None = None,
    after_snapshot: dict | None = None,
    reason: dict | None = None,
    impact: dict | None = None,
    user_visible_summary: str = "",
    explained_to_user: bool = False,
    conversation_turn_id: int | None = None,
) -> s.PlanMutationEventRecord:
    row = s.PlanMutationEventRecord(
        user_id=user_id,
        source=source,
        trigger_type=trigger_type,
        command_type=command_type,
        target_session_ids_json=_json_dumps(target_session_ids),
        before_snapshot_json=_json_dumps(before_snapshot or {}),
        after_snapshot_json=_json_dumps(after_snapshot or {}),
        reason_json=_json_dumps(reason or {}),
        impact_json=_json_dumps(impact or {}),
        user_visible_summary=user_visible_summary,
        explained_to_user=explained_to_user,
        conversation_turn_id=conversation_turn_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_adaptation_event(db: Session, user_id: int, entry: AdaptationLogEntry) -> s.AdaptationEventRecord:
    row = s.AdaptationEventRecord(
        user_id=user_id,
        reason_code=entry.reason_code,
        adaptation_level=entry.adaptation_level,
        week_mission_status=entry.week_mission_status,
        trajectory_impact=entry.trajectory_impact,
        scenario_type=entry.scenario_type,
        mutation_type=entry.mutation_type,
        summary=entry.summary,
        what_changed=entry.what_changed,
        what_protected=entry.what_protected,
        user_message=entry.user_message,
        source_text=entry.source_text,
        change_cost=entry.change_cost,
        stability_penalty=entry.stability_penalty,
        protected_session_ids_json=_json_dumps(list(entry.protected_session_ids)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_latest_adaptation_event(db: Session, user_id: int) -> AdaptationLogEntry | None:
    row = (
        db.query(s.AdaptationEventRecord)
        .filter(s.AdaptationEventRecord.user_id == user_id)
        .order_by(s.AdaptationEventRecord.created_at.desc(), s.AdaptationEventRecord.id.desc())
        .first()
    )
    return to_domain_adaptation_event(row) if row else None


def get_recent_adaptation_events(db: Session, user_id: int, *, limit: int = 4) -> list[AdaptationLogEntry]:
    rows = (
        db.query(s.AdaptationEventRecord)
        .filter(s.AdaptationEventRecord.user_id == user_id)
        .order_by(s.AdaptationEventRecord.created_at.desc(), s.AdaptationEventRecord.id.desc())
        .limit(limit)
        .all()
    )
    return [to_domain_adaptation_event(row) for row in rows]


def add_activity(
    db: Session,
    *,
    user_id: int,
    source: str,
    external_id: str | None = None,
    scheduled_session_id: int | None = None,
    sport_type: str,
    title: str,
    duration_min: int | None,
    distance_m: float | None,
    elevation_m: float | None,
    perceived_load: int | None,
    note: str,
    started_at,
    matched_day: str | None,
    match_reason: str,
    avg_hr: float | None = None,
    max_hr: float | None = None,
    avg_speed: float | None = None,
    calories: float | None = None,
    suffer_score: int | None = None,
    tss: float | None = None,
    map_polyline: str | None = None,
    start_latlng: str | None = None,
) -> s.Activity:
    activity = s.Activity(
        user_id=user_id,
        source=source,
        external_id=external_id,
        scheduled_session_id=scheduled_session_id,
        sport_type=sport_type,
        title=title,
        duration_min=duration_min,
        distance_m=distance_m,
        elevation_m=elevation_m,
        perceived_load=perceived_load,
        note=note,
        started_at=started_at,
        matched_day=matched_day,
        match_reason=match_reason,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_speed=avg_speed,
        calories=calories,
        suffer_score=suffer_score,
        tss=tss,
        map_polyline=map_polyline,
        start_latlng=start_latlng,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def replace_user_lists(
    db: Session,
    user: s.User,
    *,
    sports: list[str],
    constraints: list[str],
    preferences: list[str],
) -> None:
    db.query(s.UserSport).filter(s.UserSport.user_id == user.id).delete()
    db.query(s.UserConstraint).filter(s.UserConstraint.user_id == user.id).delete()
    db.query(s.UserPreference).filter(s.UserPreference.user_id == user.id).delete()

    for index, sport in enumerate(sports):
        db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=index))
    for text in constraints:
        db.add(s.UserConstraint(user_id=user.id, text=text))
    for text in preferences:
        db.add(s.UserPreference(user_id=user.id, text=text))

    db.commit()


def replace_user_facts(db: Session, user_id: int, facts: list[dict]) -> None:
    db.query(s.UserFact).filter(s.UserFact.user_id == user_id).delete()
    for fact in facts:
        normalized = normalize_fact_payload(fact)
        db.add(
            s.UserFact(
                user_id=user_id,
                category=normalized["category"],
                key=normalized["key"],
                value=normalized["value"],
                source=normalized.get("source", "onboarding"),
                confidence=normalized.get("confidence", 1.0),
                confirmed=normalized.get("confirmed", True),
                active=normalized.get("active", True),
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "medium"),
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
            )
        )
    db.commit()


def upsert_facts(db: Session, user_id: int, facts: list[dict]) -> list[s.UserFact]:
    saved: list[s.UserFact] = []
    for fact in facts:
        normalized = normalize_fact_payload(fact)
        category = normalized.get("category", "").strip()
        key = normalized.get("key", "").strip()
        value = normalized.get("value", "").strip()
        if not category or not key:
            continue

        row = (
            db.query(s.UserFact)
            .filter(s.UserFact.user_id == user_id, s.UserFact.category == category, s.UserFact.key == key)
            .first()
        )
        action = fact.get("action", "upsert")

        if action == "archive":
            if row:
                row.active = False
                if value:
                    row.value = value
                saved.append(row)
            continue

        if not value:
            continue

        if row is None:
            row = s.UserFact(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=normalized.get("source", "conversation"),
                confidence=float(normalized.get("confidence", 0.7)),
                confirmed=bool(normalized.get("confirmed", False)),
                active=True,
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "medium"),
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
            )
            db.add(row)
        else:
            row.value = value
            row.source = normalized.get("source", row.source)
            row.confidence = max(row.confidence, float(normalized.get("confidence", row.confidence)))
            row.confirmed = row.confirmed or bool(normalized.get("confirmed", False))
            row.active = True
            row.urgency = normalized.get("urgency", row.urgency)
            row.ttl = normalized.get("ttl", row.ttl)
            row.affects_json = _json_dumps(normalized.get("affects", _json_loads_list(row.affects_json)))
            row.expires_at = normalized.get("expires_at")

        saved.append(row)

    db.commit()
    return saved


def upsert_working_memory(db: Session, user_id: int, entries: list[dict]) -> list[s.WorkingMemoryEntry]:
    saved: list[s.WorkingMemoryEntry] = []
    for entry in entries:
        normalized = normalize_fact_payload(entry)
        category = normalized.get("category", "").strip()
        key = normalized.get("key", "").strip()
        value = normalized.get("value", "").strip()
        if not category or not key:
            continue

        row = (
            db.query(s.WorkingMemoryEntry)
            .filter(s.WorkingMemoryEntry.user_id == user_id, s.WorkingMemoryEntry.category == category, s.WorkingMemoryEntry.key == key)
            .first()
        )
        action = entry.get("action", "upsert")

        if action == "archive":
            if row:
                row.active = False
                if value:
                    row.value = value
                saved.append(row)
            continue

        if not value:
            continue

        scope = str(entry.get("scope") or "conversation")
        if row is None:
            row = s.WorkingMemoryEntry(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=normalized.get("source", "conversation"),
                confidence=float(normalized.get("confidence", 0.7)),
                confirmed=bool(normalized.get("confirmed", False)),
                active=True,
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "short"),
                scope=scope,
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
            )
            db.add(row)
        else:
            row.value = value
            row.source = normalized.get("source", row.source)
            row.confidence = max(row.confidence, float(normalized.get("confidence", row.confidence)))
            row.confirmed = row.confirmed or bool(normalized.get("confirmed", False))
            row.active = True
            row.urgency = normalized.get("urgency", row.urgency)
            row.ttl = normalized.get("ttl", row.ttl)
            row.scope = scope or row.scope
            row.affects_json = _json_dumps(normalized.get("affects", _json_loads_list(row.affects_json)))
            row.expires_at = normalized.get("expires_at")

        saved.append(row)

    db.commit()
    return saved


def purge_expired_working_memory(db: Session, user_id: int | None = None) -> int:
    query = db.query(s.WorkingMemoryEntry).filter(s.WorkingMemoryEntry.active.is_(True))
    if user_id is not None:
        query = query.filter(s.WorkingMemoryEntry.user_id == user_id)
    rows = query.all()
    archived = 0
    for row in rows:
        if fact_is_current(row):
            continue
        row.active = False
        archived += 1
    if archived:
        db.commit()
    return archived


def sync_user_patterns(db: Session, user_id: int, patterns: list[dict]) -> tuple[int, int]:
    normalized_patterns = [dict(pattern) for pattern in patterns]
    active_keys = {
        (str(pattern.get("pattern_type") or "").strip(), str(pattern.get("key") or "").strip())
        for pattern in normalized_patterns
        if str(pattern.get("pattern_type") or "").strip() and str(pattern.get("key") or "").strip()
    }
    existing_rows = (
        db.query(s.UserPattern)
        .filter(s.UserPattern.user_id == user_id)
        .all()
    )
    by_identity = {
        (row.pattern_type, row.key): row
        for row in existing_rows
    }
    upserted = 0
    archived = 0

    for pattern in normalized_patterns:
        category = str(pattern.get("category") or "").strip()
        pattern_type = str(pattern.get("pattern_type") or "").strip()
        key = str(pattern.get("key") or "").strip()
        value = str(pattern.get("value") or "").strip()
        if not category or not pattern_type or not key or not value:
            continue

        row = by_identity.get((pattern_type, key))
        if row is None:
            row = s.UserPattern(
                user_id=user_id,
                category=category,
                pattern_type=pattern_type,
                key=key,
                value=value,
                source=str(pattern.get("source") or "maintenance"),
                confidence=float(pattern.get("confidence", 0.7) or 0.7),
                confirmed=bool(pattern.get("confirmed", True)),
                active=True,
                urgency=str(pattern.get("urgency") or "medium"),
                ttl=str(pattern.get("ttl") or "long"),
                evidence_count=int(pattern.get("evidence_count", 1) or 1),
                affects_json=_json_dumps(pattern.get("affects", [])),
                metadata_json=_json_dumps(pattern.get("metadata", {})),
                first_seen_at=pattern.get("first_seen_at"),
                last_seen_at=pattern.get("last_seen_at"),
            )
            db.add(row)
            by_identity[(pattern_type, key)] = row
        else:
            row.category = category
            row.value = value
            row.source = str(pattern.get("source") or row.source)
            row.confidence = float(pattern.get("confidence", row.confidence) or row.confidence)
            row.confirmed = bool(pattern.get("confirmed", row.confirmed))
            row.active = True
            row.urgency = str(pattern.get("urgency") or row.urgency)
            row.ttl = str(pattern.get("ttl") or row.ttl)
            row.evidence_count = int(pattern.get("evidence_count", row.evidence_count) or row.evidence_count)
            row.affects_json = _json_dumps(pattern.get("affects", _json_loads_list(row.affects_json)))
            row.metadata_json = _json_dumps(pattern.get("metadata", _json_loads_json(row.metadata_json)))
            row.first_seen_at = pattern.get("first_seen_at") or row.first_seen_at
            row.last_seen_at = pattern.get("last_seen_at") or row.last_seen_at
        upserted += 1

    for row in existing_rows:
        identity = (row.pattern_type, row.key)
        if row.source != "maintenance" or identity in active_keys or not row.active:
            continue
        row.active = False
        archived += 1

    db.commit()
    return upserted, archived


def save_fitness_snapshot(db: Session, snapshot: FitnessSnapshot) -> s.FitnessSnapshotRecord:
    row = (
        db.query(s.FitnessSnapshotRecord)
        .filter(
            s.FitnessSnapshotRecord.user_id == snapshot.user_id,
            s.FitnessSnapshotRecord.snapshot_date == snapshot.date,
        )
        .first()
    )
    if row is None:
        row = s.FitnessSnapshotRecord(user_id=snapshot.user_id, snapshot_date=snapshot.date)
        db.add(row)

    row.ctl = snapshot.ctl
    row.atl = snapshot.atl
    row.tsb = snapshot.tsb
    row.ramp_rate = snapshot.ramp_rate
    row.weekly_target_tss = snapshot.weekly_target_tss
    row.weekly_actual_tss = snapshot.weekly_actual_tss
    row.completion_rate_14d = snapshot.completion_rate_14d
    row.key_sessions_done_14d = snapshot.key_sessions_done_14d
    row.volume_sessions_done_14d = snapshot.volume_sessions_done_14d
    row.sport_ctl_json = _json_dumps(snapshot.sport_ctl)
    row.sport_volume_hours_json = _json_dumps(snapshot.sport_volume_hours)
    db.commit()
    db.refresh(row)
    return row


def save_readiness_snapshot(db: Session, readiness: ReadinessState) -> s.ReadinessSnapshotRecord:
    row = (
        db.query(s.ReadinessSnapshotRecord)
        .filter(
            s.ReadinessSnapshotRecord.user_id == readiness.user_id,
            s.ReadinessSnapshotRecord.snapshot_date == readiness.date,
        )
        .first()
    )
    if row is None:
        row = s.ReadinessSnapshotRecord(user_id=readiness.user_id, snapshot_date=readiness.date)
        db.add(row)

    row.physical = readiness.physical
    row.mental = readiness.mental
    row.logistical = readiness.logistical
    row.injury_risk = readiness.injury_risk
    row.risk_flags_json = _json_dumps(list(readiness.risk_flags))
    row.summary = readiness.summary
    db.commit()
    db.refresh(row)
    return row


def save_planning_decision(db: Session, decision: PlanningDecision) -> s.PlanningDecisionRecord:
    row = (
        db.query(s.PlanningDecisionRecord)
        .filter(
            s.PlanningDecisionRecord.user_id == decision.user_id,
            s.PlanningDecisionRecord.week_start == decision.week_start,
        )
        .first()
    )
    if row is None:
        row = s.PlanningDecisionRecord(user_id=decision.user_id, week_start=decision.week_start)
        db.add(row)

    row.decision_version = decision.decision_version
    row.planning_mode = decision.planning_mode
    row.adaptation_level = decision.adaptation_level
    row.adaptation_scope = decision.adaptation_scope
    row.weekly_target_tss = decision.weekly_target_tss
    row.intensity_distribution = decision.intensity_distribution
    row.key_session_count = decision.key_session_count
    row.strength_session_count = decision.strength_session_count
    row.long_session = decision.long_session
    row.rationale_json = _json_dumps(list(decision.rationale))
    row.adaptations_json = _json_dumps(list(decision.adaptations))
    row.risk_flags_json = _json_dumps(list(decision.risk_flags))
    db.commit()
    db.refresh(row)
    return row


def replace_plan(
    db: Session,
    user_id: int,
    *,
    intention: str,
    summary: str,
    days: list[dict],
    timezone_name: str | None = None,
    mesocycle_week: int = 1,
    mesocycle_number: int = 1,
    total_weeks: int = 1,
) -> s.WeeklyPlan:
    plans = db.query(s.WeeklyPlan).filter(s.WeeklyPlan.user_id == user_id).all()
    plan_ids = [plan.id for plan in plans]
    if plan_ids:
        day_ids = [
            row[0]
            for row in db.query(s.DayPlan.id).filter(s.DayPlan.weekly_plan_id.in_(plan_ids)).all()
        ]
        if day_ids:
            db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id.in_(day_ids)).delete(synchronize_session=False)
            db.query(s.WatchItem).filter(s.WatchItem.day_plan_id.in_(day_ids)).delete(synchronize_session=False)
            db.query(s.DayPlan).filter(s.DayPlan.id.in_(day_ids)).delete(synchronize_session=False)
        db.query(s.WeeklyPlan).filter(s.WeeklyPlan.id.in_(plan_ids)).delete(synchronize_session=False)
    db.commit()
    for stale_plan in plans:
        if db.object_session(stale_plan) is db:
            db.expunge(stale_plan)

    plan = s.WeeklyPlan(
        user_id=user_id,
        intention=intention,
        summary=summary,
        status="active",
        mesocycle_week=mesocycle_week,
        mesocycle_number=mesocycle_number,
        total_weeks=max(1, int(total_weeks or 1)),
    )
    db.add(plan)
    db.flush()

    for sort_order, day in enumerate(days):
        change_notes = day.pop("change_notes", [])
        watch_items = day.pop("watch_items", [])
        day_row = s.DayPlan(weekly_plan_id=plan.id, sort_order=sort_order, **day)
        db.add(day_row)
        db.flush()
        for title, detail in change_notes:
            db.add(s.ChangeNote(day_plan_id=day_row.id, title=title, detail=detail))
        for title, detail in watch_items:
            db.add(s.WatchItem(day_plan_id=day_row.id, title=title, detail=detail))

    db.commit()
    db.refresh(plan)
    sync_scheduled_sessions_for_plan(db, user_id=user_id, plan=plan, timezone_name=timezone_name)
    return plan


def sync_scheduled_sessions_for_plan(
    db: Session,
    *,
    user_id: int,
    plan: s.WeeklyPlan,
    timezone_name: str | None,
) -> None:
    local_now = get_local_now(timezone_name)
    current_date = local_now.date()
    current_day_index = local_now.weekday()

    for day_row in plan.days:
        target_day_index = DAY_KEYS.index(day_row.day)
        scheduled_date = current_date + timedelta(days=target_day_index - current_day_index)
        if scheduled_date < current_date:
            continue

        scheduled_dt = datetime.combine(scheduled_date, datetime.min.time())
        session = get_scheduled_session_for_date(
            db,
            user_id,
            day=day_row.day,
            scheduled_date=scheduled_dt,
        )
        if session is None:
            session = s.ScheduledSession(
                user_id=user_id,
                day=day_row.day,
                label=day_row.label,
                scheduled_date=scheduled_dt,
                source_plan_created_at=plan.created_at,
            )
            db.add(session)

        session.label = day_row.label
        session.source_plan_created_at = plan.created_at
        session.sport_type = day_row.sport_type
        session.session_type = day_row.session_type
        session.session_title = day_row.session_title
        session.session_goal = day_row.session_goal
        session.session_note = day_row.session_note
        session.session_description = day_row.session_description
        session.duration_min = day_row.duration_min
        session.intensity = day_row.intensity
        session.load_score = day_row.load_score
        session.priority = day_row.priority
        session.nutrition_focus = day_row.nutrition_focus
        session.flexibility = day_row.flexibility
        if session.completion_status != "done":
            session.completion_status = day_row.completion_status

    db.commit()


def mark_day_completed(db: Session, plan_id: int, day: str) -> bool:
    """Mark a day as done when an activity matches it. Returns True if updated."""
    day_row = get_day_plan(db, plan_id, day)
    if not day_row:
        return False
    if day_row.completion_status == "done":
        return False  # already done
    day_row.completion_status = "done"
    db.commit()
    return True


def mark_scheduled_session_completed(db: Session, session_id: int | None) -> bool:
    if session_id is None:
        return False
    session = db.query(s.ScheduledSession).filter(s.ScheduledSession.id == session_id).first()
    if not session or session.completion_status == "done":
        return False
    session.completion_status = "done"
    db.commit()
    return True


def set_scheduled_session_status(db: Session, session_id: int, status: str) -> s.ScheduledSession | None:
    session = db.query(s.ScheduledSession).filter(s.ScheduledSession.id == session_id).first()
    if session is None:
        return None
    session.completion_status = status
    db.commit()
    db.refresh(session)
    return session


def get_current_week_day_plan_for_session(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> tuple[s.WeeklyPlan | None, s.DayPlan | None]:
    week_dates = current_week_dates(user.timezone)
    if week_dates.get(session.day) != session.scheduled_date.date():
        return None, None
    plan = get_active_plan(db, user.id)
    return plan, get_day_plan(db, plan.id, session.day)


def resync_plan_sessions(db: Session, plan_id: int, *, timezone_name: str | None) -> bool:
    plan = get_plan_optional(db, plan_id)
    if plan is None:
        return False
    sync_scheduled_sessions_for_plan(db, user_id=plan.user_id, plan=plan, timezone_name=timezone_name)
    return True


def get_yesterday_status(db: Session, plan_id: int, today_key: str) -> tuple[str | None, str | None]:
    """Return (day_key, completion_status) for yesterday relative to today_key."""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    idx = day_order.index(today_key) if today_key in day_order else 0
    yesterday_key = day_order[idx - 1]  # wraps: monday → sunday
    day_row = get_day_plan(db, plan_id, yesterday_key)
    if not day_row:
        return yesterday_key, None
    return yesterday_key, day_row.completion_status


def move_session(db: Session, plan_id: int, from_day: str, to_day: str) -> None:
    """Move a session from one day to another. Source day becomes flexible/light."""
    src = get_day_plan(db, plan_id, from_day)
    dst = get_day_plan(db, plan_id, to_day)
    if not src or not dst:
        return

    # Copy session from source to destination
    dst.sport_type = src.sport_type
    dst.session_type = src.session_type
    dst.session_title = src.session_title
    dst.session_goal = src.session_goal
    dst.session_note = src.session_note
    dst.session_description = src.session_description
    dst.duration_min = src.duration_min
    dst.intensity = src.intensity
    dst.load_score = src.load_score
    dst.priority = src.priority
    dst.nutrition_focus = src.nutrition_focus
    dst.flexibility = "stable"
    dst.completion_status = "adapted"

    # Source becomes light
    src.sport_type = "rest"
    src.session_type = "rest"
    src.session_title = "Journee flexible"
    src.session_goal = "Creneau libere — repos ou sortie tres legere selon ressenti"
    src.session_note = "Seance deplacee. Profites-en pour recuperer ou faire un footing facile."
    src.session_description = ""
    src.duration_min = None
    src.intensity = "easy"
    src.load_score = 0
    src.priority = "Leger"
    src.nutrition_focus = "Reste simple. Laisse de la marge a la suite de la semaine."
    src.flexibility = "flexible"
    src.completion_status = "adapted"

    db.commit()


def set_change_notes(db: Session, day_plan_id: int, notes: list[tuple[str, str]]) -> None:
    """Replace all change notes for a day. notes = [(title, detail), ...]"""
    db.query(s.ChangeNote).filter(s.ChangeNote.day_plan_id == day_plan_id).delete()
    for title, detail in notes:
        db.add(s.ChangeNote(day_plan_id=day_plan_id, title=title, detail=detail))
    db.commit()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_loads_dict(raw_value: str) -> dict[str, float]:
    if not raw_value:
        return {}
    return {str(key): float(value) for key, value in json.loads(raw_value).items()}


def _json_loads_json(raw_value: str) -> dict[str, object]:
    if not raw_value:
        return {}
    loaded = json.loads(raw_value)
    return loaded if isinstance(loaded, dict) else {}


def _json_loads_list(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    return [str(value) for value in json.loads(raw_value)]


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
