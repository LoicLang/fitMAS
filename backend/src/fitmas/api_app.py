from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s, strava
from fitmas.api_read import _build_recent_activity, _build_today_fitness, _build_today_view
from fitmas.app_views import build_app_calendar, build_app_evolution, build_app_overview, build_session_detail
from fitmas.athlete_profile import build_athlete_profile
from fitmas.calibration_status import build_calibration_status
from fitmas.db import get_db
from fitmas.performance_overview import build_performance_overview
from fitmas.performance_stats import build_training_load_stats
from fitmas.planning_contract import (
    build_availability_state,
    build_planning_contract,
    build_session_policies,
    build_week_mission,
)
from fitmas.time_context import get_local_now
from fitmas.week_context import (
    build_deterministic_coach_reading,
    build_next_week_cadrage,
    build_planning_context,
    build_week_summary,
)

router = APIRouter()


def _build_app_context_bundle(
    db: Session,
    *,
    user: s.User,
    today_date: date,
    scheduled_sessions: list[s.ScheduledSession],
    activities: list[s.Activity],
    planning_decision: s.PlanningDecisionRecord | None,
    week_plan,
    recent_adaptations_limit: int,
) -> dict:
    active_memory = repo.get_active_memory_items(
        db,
        user.id,
        profile_limit=24,
        working_limit=24,
        include_patterns=True,
        pattern_limit=6,
        total_limit=36,
    )
    profile_snapshot = build_athlete_profile(user, facts=active_memory)
    session_policies = build_session_policies(today=today_date, scheduled_sessions=scheduled_sessions)
    planning_contract = build_planning_contract(
        today=today_date,
        profile=profile_snapshot,
        week_plan=week_plan,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
    )
    availability_state = build_availability_state(profile_snapshot)
    week_mission = build_week_mission(
        today=today_date,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
        session_policies=session_policies,
    )
    latest_adaptation = repo.get_latest_adaptation_event(db, user.id)
    recent_adaptations = repo.get_recent_adaptation_events(db, user.id, limit=recent_adaptations_limit)
    calibration_status = build_calibration_status(
        profile=profile_snapshot,
        memory_items=active_memory,
        activities=activities,
        adaptation_events=recent_adaptations,
        today=today_date,
    )
    return {
        "active_memory": active_memory,
        "profile_snapshot": profile_snapshot,
        "session_policies": session_policies,
        "planning_contract": planning_contract,
        "availability_state": availability_state,
        "week_mission": week_mission,
        "latest_adaptation": latest_adaptation,
        "recent_adaptations": recent_adaptations,
        "calibration_status": calibration_status,
    }


@router.get("/api/v0/app/overview")
def get_app_overview(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    today_view = _build_today_view(db, user=user, session=today_session).model_dump() if today_session is not None else None
    today_date = get_local_now(user.timezone).date()
    week_plan = repo.to_pydantic_plan(repo.get_active_plan(db, user.id))
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=week_plan,
        planning_decision=planning_decision,
    )
    strava_status = {
        "configured": strava.is_configured(),
        "connected": repo.get_strava_connection(db, user.id) is not None,
        "last_sync_at": None,
    }
    connection = repo.get_strava_connection(db, user.id)
    if connection and connection.last_sync_at:
        strava_status["last_sync_at"] = connection.last_sync_at.isoformat()
    readiness_row = repo.get_latest_readiness_snapshot_record(db, user.id)
    readiness = repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
    context_bundle = _build_app_context_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        week_plan=week_plan,
        recent_adaptations_limit=4,
    )

    week_summary = build_week_summary(
        today=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    planning_ctx = build_planning_context(
        planning_decision=planning_decision,
        mesocycle_week=week_plan.mesocycle_week,
        mesocycle_number=week_plan.mesocycle_number,
        is_deload=week_plan.is_deload,
        total_weeks=week_plan.total_weeks,
        readiness=readiness,
    )
    next_week = build_next_week_cadrage(
        current_mesocycle_week=week_plan.mesocycle_week,
        current_planning_mode=str(getattr(planning_decision, "planning_mode", None) or "maintain_load"),
        current_target_tss=planning_ctx["target_tss"],
    )
    coach_reading = build_deterministic_coach_reading(
        week_summary=week_summary,
        planning_context=planning_ctx,
        next_week=next_week,
        screen="overview",
    )

    overview = build_app_overview(
        today_date=today_date,
        profile=repo.to_pydantic_profile(user),
        strava_status=strava_status,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        today_view=today_view,
        session_policies=context_bundle["session_policies"],
    )
    overview["week_context"] = {
        "summary": week_summary,
        "planning": planning_ctx,
        "next_week": next_week,
        "coach_reading": coach_reading,
    }
    overview["planning_contract"] = context_bundle["planning_contract"].as_dict()
    overview["availability_state"] = context_bundle["availability_state"].as_dict()
    overview["week_mission"] = context_bundle["week_mission"].as_dict()
    overview["last_adaptation"] = context_bundle["latest_adaptation"].as_dict() if context_bundle["latest_adaptation"] else None
    overview["recent_adaptations"] = [entry.as_dict() for entry in context_bundle["recent_adaptations"]]
    overview["calibration_status"] = context_bundle["calibration_status"].as_dict()
    return overview


@router.get("/api/v0/app/calendar")
def get_app_calendar(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    month_start = date.fromisoformat(f"{month or today_date.isoformat()[:7]}-01")
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    week_plan = repo.to_pydantic_plan(repo.get_active_plan(db, user.id))
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=week_plan,
        planning_decision=planning_decision,
    )
    context_bundle = _build_app_context_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        week_plan=week_plan,
        recent_adaptations_limit=4,
    )

    calendar = build_app_calendar(
        today_date=today_date,
        month_start=month_start,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        session_policies=context_bundle["session_policies"],
    )
    calendar["planning_contract"] = context_bundle["planning_contract"].as_dict()
    calendar["availability_state"] = context_bundle["availability_state"].as_dict()
    calendar["week_mission"] = context_bundle["week_mission"].as_dict()
    calendar["last_adaptation"] = context_bundle["latest_adaptation"].as_dict() if context_bundle["latest_adaptation"] else None
    calendar["recent_adaptations"] = [entry.as_dict() for entry in context_bundle["recent_adaptations"]]
    calendar["calibration_status"] = context_bundle["calibration_status"].as_dict()
    return calendar


@router.get("/api/v0/app/evolution")
def get_app_evolution(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    week_plan = repo.to_pydantic_plan(repo.get_active_plan(db, user.id))
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=week_plan,
        planning_decision=planning_decision,
    )
    training_load = build_training_load_stats(activities, as_of_date=today_date, weeks=16)
    readiness_row = repo.get_latest_readiness_snapshot_record(db, user.id)
    readiness = repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
    context_bundle = _build_app_context_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        week_plan=week_plan,
        recent_adaptations_limit=6,
    )

    week_summary = build_week_summary(
        today=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    planning_ctx = build_planning_context(
        planning_decision=planning_decision,
        mesocycle_week=week_plan.mesocycle_week,
        mesocycle_number=week_plan.mesocycle_number,
        is_deload=week_plan.is_deload,
        total_weeks=week_plan.total_weeks,
        readiness=readiness,
    )
    next_week = build_next_week_cadrage(
        current_mesocycle_week=week_plan.mesocycle_week,
        current_planning_mode=str(getattr(planning_decision, "planning_mode", None) or "maintain_load"),
        current_target_tss=planning_ctx["target_tss"],
    )
    coach_reading = build_deterministic_coach_reading(
        week_summary=week_summary,
        planning_context=planning_ctx,
        next_week=next_week,
        screen="evolution",
    )

    evolution = build_app_evolution(
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        training_load=training_load,
    )
    evolution["week_context"] = {
        "summary": week_summary,
        "planning": planning_ctx,
        "next_week": next_week,
        "coach_reading": coach_reading,
    }
    evolution["planning_contract"] = context_bundle["planning_contract"].as_dict()
    evolution["availability_state"] = context_bundle["availability_state"].as_dict()
    evolution["week_mission"] = context_bundle["week_mission"].as_dict()
    evolution["last_adaptation"] = context_bundle["latest_adaptation"].as_dict() if context_bundle["latest_adaptation"] else None
    evolution["recent_adaptations"] = [entry.as_dict() for entry in context_bundle["recent_adaptations"]]
    evolution["calibration_status"] = context_bundle["calibration_status"].as_dict()
    return evolution


@router.get("/api/v0/sessions/{session_id}")
def get_session_detail(session_id: int, db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")

    _, day_row = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    linked_activity = next((activity for activity in session.activities if activity.sport_type == session.sport_type), None)
    recent_activity = _build_recent_activity(db, user=user, session=session)
    change_notes = [{"title": note.title, "detail": note.detail} for note in (day_row.change_notes if day_row else [])]
    watch_items = [{"title": item.title, "detail": item.detail} for item in (day_row.watch_items if day_row else [])]

    return build_session_detail(
        today_date=get_local_now(user.timezone).date(),
        session=session,
        linked_activity=repo.to_pydantic_activity(linked_activity).model_dump() if linked_activity is not None else None,
        fitness=_build_today_fitness(db, user=user).model_dump(),
        recent_activity=recent_activity.model_dump() if recent_activity is not None else None,
        change_notes=change_notes,
        watch_items=watch_items,
    )
