from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.domain.coaching import repo_conversation
from fitmas.domain.coaching.adaptation_log import AdaptationLogEntry
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.execution import repository as execution_repo
from fitmas.domain.memory import repository as memory_repo
from fitmas.domain.athlete.fitness_snapshot import FitnessSnapshot
from fitmas.domain.planning import repository as planning_repo
from fitmas.domain.planning import template_repository as template_repo
from fitmas.integrations import repository as integration_repo
from fitmas.models import (
    Activity,
    DayId,
    DayPlan,
    Message,
    MessageRole,
    Profile,
    ScheduledSession,
    UserFact,
    UserPattern,
    WeeklyPlan,
)
from fitmas.domain.planning.planning_decision import PlanningDecision
from fitmas.domain.athlete.readiness import ReadinessState
from fitmas.domain.planning.models import compute_load_band


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
    return template_repo.to_pydantic_day(day)


def to_pydantic_plan(plan: s.WeeklyPlan) -> WeeklyPlan:
    return template_repo.to_pydantic_plan(plan)


def to_pydantic_message(msg: s.CoachMessage) -> Message:
    return Message(role=MessageRole(msg.role), text=msg.text)


def to_domain_adaptation_event(record: s.AdaptationEventRecord) -> AdaptationLogEntry:
    from fitmas.domain.planning.adaptation_decision import DecisionReasonCode, TrajectoryImpact, WeekMissionStatus
    from fitmas.domain.coaching.adaptation_log import _impact_label, _mission_label, _reason_label

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
    return memory_repo.to_pydantic_fact(fact)


def to_pydantic_pattern(pattern: s.UserPattern) -> UserPattern:
    return memory_repo.to_pydantic_pattern(pattern)


def to_pydantic_activity(activity: s.Activity) -> Activity:
    return execution_repo.to_pydantic_activity(activity)


def to_domain_fitness_snapshot(row: s.FitnessSnapshotRecord) -> FitnessSnapshot:
    return athlete_repo.to_domain_fitness_snapshot(row)


def to_domain_readiness_snapshot(row: s.ReadinessSnapshotRecord) -> ReadinessState:
    return athlete_repo.to_domain_readiness_snapshot(row)


def to_domain_planning_decision(row: s.PlanningDecisionRecord) -> PlanningDecision:
    return planning_repo.to_domain_planning_decision(row)


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
    return template_repo.get_active_plan_optional(db, user_id)


def get_active_plan(db: Session, user_id: int) -> s.WeeklyPlan:
    return template_repo.get_active_plan(db, user_id)


def get_plan_optional(db: Session, plan_id: int) -> s.WeeklyPlan | None:
    return template_repo.get_plan_optional(db, plan_id)


def get_day_plan(db: Session, plan_id: int, day: str) -> s.DayPlan | None:
    return template_repo.get_day_plan(db, plan_id, day)


def get_messages(db: Session, user_id: int) -> list[s.CoachMessage]:
    return repo_conversation.get_messages(db, user_id)


def has_newer_user_message(db: Session, user_id: int, message_id: int | None) -> bool:
    return repo_conversation.has_newer_user_message(db, user_id, message_id)


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
    return memory_repo.get_active_facts(db, user_id, limit=limit)


def get_active_working_memory(db: Session, user_id: int, limit: int = 12) -> list[s.WorkingMemoryEntry]:
    return memory_repo.get_active_working_memory(db, user_id, limit=limit)


def get_active_patterns(db: Session, user_id: int, limit: int = 6) -> list[s.UserPattern]:
    return memory_repo.get_active_patterns(db, user_id, limit=limit)


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
    return memory_repo.get_active_memory_items(
        db,
        user_id,
        profile_limit=profile_limit,
        working_limit=working_limit,
        include_patterns=include_patterns,
        pattern_limit=pattern_limit,
        total_limit=total_limit,
    )


def get_latest_fitness_snapshot_record(db: Session, user_id: int) -> s.FitnessSnapshotRecord | None:
    return athlete_repo.get_latest_fitness_snapshot_record(db, user_id)


def get_latest_readiness_snapshot_record(db: Session, user_id: int) -> s.ReadinessSnapshotRecord | None:
    return athlete_repo.get_latest_readiness_snapshot_record(db, user_id)


def get_latest_planning_decision_record(db: Session, user_id: int) -> s.PlanningDecisionRecord | None:
    return planning_repo.get_latest_planning_decision_record(db, user_id)


def get_activities(db: Session, user_id: int, limit: int = 30) -> list[s.Activity]:
    return execution_repo.get_activities(db, user_id, limit=limit)


def get_recent_activity_for_sport(
    db: Session,
    user_id: int,
    *,
    sport_type: str,
    before: datetime | None = None,
) -> s.Activity | None:
    return execution_repo.get_recent_activity_for_sport(
        db,
        user_id,
        sport_type=sport_type,
        before=before,
    )


def get_activity_by_external_id(db: Session, user_id: int, external_id: str) -> s.Activity | None:
    return execution_repo.get_activity_by_external_id(db, user_id, external_id)


def get_strava_connection(db: Session, user_id: int) -> s.StravaConnection | None:
    return integration_repo.get_strava_connection(db, user_id)


def get_scheduled_sessions(
    db: Session,
    user_id: int,
    *,
    date_from: date | None = None,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    return planning_repo.get_scheduled_sessions(db, user_id, date_from=date_from, limit=limit)


def get_scheduled_sessions_for_date(
    db: Session,
    user_id: int,
    *,
    target_date: date,
) -> list[s.ScheduledSession]:
    return planning_repo.get_scheduled_sessions_for_date(db, user_id, target_date=target_date)


def get_scheduled_sessions_between_dates(
    db: Session,
    user_id: int,
    *,
    start_date: date,
    end_date: date,
    limit: int = 42,
) -> list[s.ScheduledSession]:
    return planning_repo.get_scheduled_sessions_between_dates(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


def get_scheduled_session_for_date(
    db: Session,
    user_id: int,
    *,
    day: str,
    scheduled_date: datetime,
) -> s.ScheduledSession | None:
    return planning_repo.get_scheduled_session_for_date(
        db,
        user_id,
        day=day,
        scheduled_date=scheduled_date,
    )


def get_scheduled_session(db: Session, user_id: int, session_id: int) -> s.ScheduledSession | None:
    return planning_repo.get_scheduled_session(db, user_id, session_id)


def get_today_scheduled_session(
    db: Session,
    user_id: int,
    *,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    return planning_repo.get_today_scheduled_session(db, user_id, timezone_name=timezone_name)


def find_scheduled_session_for_activity(
    db: Session,
    *,
    user_id: int,
    sport_type: str,
    started_at: datetime | None,
    timezone_name: str | None,
) -> s.ScheduledSession | None:
    return planning_repo.find_scheduled_session_for_activity(
        db,
        user_id=user_id,
        sport_type=sport_type,
        started_at=started_at,
        timezone_name=timezone_name,
    )


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
    return planning_repo.add_plan_mutation_event(
        db,
        user_id=user_id,
        source=source,
        trigger_type=trigger_type,
        command_type=command_type,
        target_session_ids=target_session_ids,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        reason=reason,
        impact=impact,
        user_visible_summary=user_visible_summary,
        explained_to_user=explained_to_user,
        conversation_turn_id=conversation_turn_id,
    )


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
    return execution_repo.add_activity(
        db,
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
    memory_repo.replace_user_facts(db, user_id, facts)


def upsert_facts(db: Session, user_id: int, facts: list[dict]) -> list[s.UserFact]:
    return memory_repo.upsert_facts(db, user_id, facts)


def upsert_working_memory(db: Session, user_id: int, entries: list[dict]) -> list[s.WorkingMemoryEntry]:
    return memory_repo.upsert_working_memory(db, user_id, entries)


def purge_expired_working_memory(db: Session, user_id: int | None = None) -> int:
    return memory_repo.purge_expired_working_memory(db, user_id)


def sync_user_patterns(db: Session, user_id: int, patterns: list[dict]) -> tuple[int, int]:
    return memory_repo.sync_user_patterns(db, user_id, patterns)


def save_fitness_snapshot(db: Session, snapshot: FitnessSnapshot) -> s.FitnessSnapshotRecord:
    return athlete_repo.save_fitness_snapshot(db, snapshot)


def save_readiness_snapshot(db: Session, readiness: ReadinessState) -> s.ReadinessSnapshotRecord:
    return athlete_repo.save_readiness_snapshot(db, readiness)


def save_planning_decision(db: Session, decision: PlanningDecision) -> s.PlanningDecisionRecord:
    return planning_repo.save_planning_decision(db, decision)


def replace_plan(
    db: Session,
    user_id: int,
    *,
    intention: str,
    summary: str,
    days: list[dict],
    timezone_name: str | None = None,
    now: datetime | None = None,
    mesocycle_week: int = 1,
    mesocycle_number: int = 1,
    total_weeks: int = 1,
) -> s.WeeklyPlan:
    return template_repo.replace_plan(
        db,
        user_id,
        intention=intention,
        summary=summary,
        days=days,
        timezone_name=timezone_name,
        now=now,
        mesocycle_week=mesocycle_week,
        mesocycle_number=mesocycle_number,
        total_weeks=total_weeks,
    )


def sync_scheduled_sessions_for_plan(
    db: Session,
    *,
    user_id: int,
    plan: s.WeeklyPlan,
    timezone_name: str | None,
    now: datetime | None = None,
) -> None:
    template_repo.sync_scheduled_sessions_for_plan(
        db,
        user_id=user_id,
        plan=plan,
        timezone_name=timezone_name,
        now=now,
    )


def mark_day_completed(db: Session, plan_id: int, day: str) -> bool:
    return template_repo.mark_day_completed(db, plan_id, day)


def mark_scheduled_session_completed(db: Session, session_id: int | None) -> bool:
    return planning_repo.mark_scheduled_session_completed(db, session_id)


def set_scheduled_session_status(db: Session, session_id: int, status: str) -> s.ScheduledSession | None:
    return planning_repo.set_scheduled_session_status(db, session_id, status)


def get_current_week_day_plan_for_session(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> tuple[s.WeeklyPlan | None, s.DayPlan | None]:
    return template_repo.get_current_week_day_plan_for_session(db, user=user, session=session)


def resync_plan_sessions(db: Session, plan_id: int, *, timezone_name: str | None) -> bool:
    return template_repo.resync_plan_sessions(db, plan_id, timezone_name=timezone_name)


def get_yesterday_status(db: Session, plan_id: int, today_key: str) -> tuple[str | None, str | None]:
    return template_repo.get_yesterday_status(db, plan_id, today_key)


def move_session(db: Session, plan_id: int, from_day: str, to_day: str) -> None:
    template_repo.move_session(db, plan_id, from_day, to_day)


def set_change_notes(db: Session, day_plan_id: int, notes: list[tuple[str, str]]) -> None:
    template_repo.set_change_notes(db, day_plan_id, notes)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_loads_dict(raw_value: str) -> dict[str, float]:
    if not raw_value:
        return {}
    return {str(key): float(value) for key, value in json.loads(raw_value).items()}


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
