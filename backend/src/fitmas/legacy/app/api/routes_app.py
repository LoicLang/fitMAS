from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.integrations import strava
from fitmas.legacy.integrations import repository as integration_repo
from fitmas.legacy.app.api.routes_read import _build_recent_activity, _build_today_fitness, _build_today_view
from fitmas.legacy.app.api.app_views import build_app_calendar, build_app_evolution, build_app_overview, build_session_detail
from fitmas.legacy.domain.coaching.coach_state import build_coach_state_bundle
from fitmas.legacy.core.db import get_db
from fitmas.legacy.domain.athlete import repository as athlete_repo
from fitmas.legacy.domain.athlete.performance_overview import build_performance_overview
from fitmas.legacy.domain.athlete.performance_stats import build_training_load_stats
from fitmas.legacy.domain.execution.recent_reality import build_recent_reality_window
from fitmas.legacy.domain.planning import repository as planning_repo
from fitmas.legacy.core.time_context import get_local_now
from fitmas.legacy.domain.execution import repository as execution_repo
from fitmas.legacy.domain.memory import repository as memory_repo

router = APIRouter()


def _app_source_is_v0() -> bool:
    """True when the webapp should read the live V0 store instead of the legacy DB."""
    return os.getenv("FITMAS_APP_SOURCE", "").strip().lower() == "v0"


def _v0_neutral_bundle(calendar: dict) -> dict:
    """Stub the legacy-only coach aggregates (no V0 equivalent) with neutral shapes.

    The exact shapes the React frontend expects are verified at render time (Slice 3);
    these defaults keep the API response well-formed and the legacy path untouched.
    """
    calendar["planning_contract"] = {}
    calendar["availability_state"] = {}
    calendar["week_mission"] = {}
    calendar["last_adaptation"] = None
    calendar["recent_adaptations"] = []
    calendar["calibration_status"] = {}
    return calendar


def _v0_calendar(month: str | None) -> dict:
    """Build the calendar view from the live V0 store (FITMAS_APP_SOURCE=v0)."""
    from fitmas.legacy.app.api import v0_source

    sessions = v0_source.get_scheduled_sessions()
    activities = v0_source.get_activities()
    today_date = date.today()
    month_start = date.fromisoformat(f"{month or today_date.isoformat()[:7]}-01")
    performance_overview = build_performance_overview(
        user_id=1,
        timezone_name=None,
        activities=activities,
        scheduled_sessions=sessions,
        planning_decision=None,
    )
    calendar = build_app_calendar(
        today_date=today_date,
        month_start=month_start,
        scheduled_sessions=sessions,
        activities=activities,
        performance_overview=performance_overview,
        session_policies=(),
    )
    return _v0_neutral_bundle(calendar)


def _v0_profile_stub():
    from fitmas.legacy.domain.athlete.view_models import Profile

    return Profile(
        name="Athlete",
        age=30,
        objective="",
        coaching_style="direct",
        constraints=[],
        preferences=[],
        integrations=[],
    )


def _v0_overview() -> dict:
    """Build the overview (landing) view from the live V0 store (FITMAS_APP_SOURCE=v0)."""
    from fitmas.legacy.app.api import v0_source

    sessions = v0_source.get_scheduled_sessions()
    activities = v0_source.get_activities()
    today_date = date.today()
    performance_overview = build_performance_overview(
        user_id=1,
        timezone_name=None,
        activities=activities,
        scheduled_sessions=sessions,
        planning_decision=None,
    )
    strava_status = {"configured": strava.is_configured(), "connected": False, "last_sync_at": None}
    overview = build_app_overview(
        today_date=today_date,
        profile=_v0_profile_stub(),
        strava_status=strava_status,
        scheduled_sessions=sessions,
        activities=activities,
        performance_overview=performance_overview,
        today_view=None,
        session_policies=(),
    )
    overview["week_context"] = {"summary": "", "planning": {}, "next_week": {}, "coach_reading": ""}
    return _v0_neutral_bundle(overview)

@router.get("/api/v0/app/overview")
def get_app_overview(db: Session = Depends(get_db)) -> dict:
    if _app_source_is_v0():
        return _v0_overview()
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    scheduled_sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=84)
    activities = execution_repo.get_activities(db, user.id, limit=500)
    planning_decision = planning_repo.get_latest_planning_decision_record(db, user.id)
    today_session = planning_repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    today_view = _build_today_view(db, user=user, session=today_session).model_dump() if today_session is not None else None
    today_date = get_local_now(user.timezone).date()
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        planning_decision=planning_decision,
    )
    strava_status = {
        "configured": strava.is_configured(),
        "connected": integration_repo.get_strava_connection(db, user.id) is not None,
        "last_sync_at": None,
    }
    connection = integration_repo.get_strava_connection(db, user.id)
    if connection and connection.last_sync_at:
        strava_status["last_sync_at"] = connection.last_sync_at.isoformat()
    readiness_row = athlete_repo.get_latest_readiness_snapshot_record(db, user.id)
    readiness = athlete_repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
    coach_bundle = build_coach_state_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        recent_adaptations_limit=4,
        readiness=readiness,
        screen="overview",
    )

    overview = build_app_overview(
        today_date=today_date,
        profile=athlete_repo.to_pydantic_profile(user),
        strava_status=strava_status,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        today_view=today_view,
        session_policies=coach_bundle.session_policies,
    )
    overview["week_context"] = {
        "summary": coach_bundle.week_summary,
        "planning": coach_bundle.planning_context,
        "next_week": coach_bundle.next_week,
        "coach_reading": coach_bundle.coach_reading,
    }
    overview["planning_contract"] = coach_bundle.planning_contract.as_dict()
    overview["availability_state"] = coach_bundle.availability_state.as_dict()
    overview["week_mission"] = coach_bundle.week_mission.as_dict()
    overview["last_adaptation"] = coach_bundle.latest_adaptation.as_dict() if coach_bundle.latest_adaptation else None
    overview["recent_adaptations"] = [entry.as_dict() for entry in coach_bundle.recent_adaptations]
    overview["calibration_status"] = coach_bundle.calibration_status.as_dict()
    return overview


@router.get("/api/v0/app/calendar")
def get_app_calendar(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> dict:
    if _app_source_is_v0():
        return _v0_calendar(month)
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    month_start = date.fromisoformat(f"{month or today_date.isoformat()[:7]}-01")
    scheduled_sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = execution_repo.get_activities(db, user.id, limit=500)
    planning_decision = planning_repo.get_latest_planning_decision_record(db, user.id)
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        planning_decision=planning_decision,
    )
    coach_bundle = build_coach_state_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        recent_adaptations_limit=4,
        screen="calendar",
    )

    calendar = build_app_calendar(
        today_date=today_date,
        month_start=month_start,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        session_policies=coach_bundle.session_policies,
    )
    calendar["planning_contract"] = coach_bundle.planning_contract.as_dict()
    calendar["availability_state"] = coach_bundle.availability_state.as_dict()
    calendar["week_mission"] = coach_bundle.week_mission.as_dict()
    calendar["last_adaptation"] = coach_bundle.latest_adaptation.as_dict() if coach_bundle.latest_adaptation else None
    calendar["recent_adaptations"] = [entry.as_dict() for entry in coach_bundle.recent_adaptations]
    calendar["calibration_status"] = coach_bundle.calibration_status.as_dict()
    return calendar


@router.get("/api/v0/app/evolution")
def get_app_evolution(db: Session = Depends(get_db)) -> dict:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    scheduled_sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = execution_repo.get_activities(db, user.id, limit=500)
    planning_decision = planning_repo.get_latest_planning_decision_record(db, user.id)
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        planning_decision=planning_decision,
    )
    training_load = build_training_load_stats(activities, as_of_date=today_date, weeks=16)
    readiness_row = athlete_repo.get_latest_readiness_snapshot_record(db, user.id)
    readiness = athlete_repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
    coach_bundle = build_coach_state_bundle(
        db,
        user=user,
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        planning_decision=planning_decision,
        recent_adaptations_limit=6,
        readiness=readiness,
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
        "summary": coach_bundle.week_summary,
        "planning": coach_bundle.planning_context,
        "next_week": coach_bundle.next_week,
        "coach_reading": coach_bundle.coach_reading,
    }
    evolution["planning_contract"] = coach_bundle.planning_contract.as_dict()
    evolution["availability_state"] = coach_bundle.availability_state.as_dict()
    evolution["week_mission"] = coach_bundle.week_mission.as_dict()
    evolution["last_adaptation"] = coach_bundle.latest_adaptation.as_dict() if coach_bundle.latest_adaptation else None
    evolution["recent_adaptations"] = [entry.as_dict() for entry in coach_bundle.recent_adaptations]
    evolution["calibration_status"] = coach_bundle.calibration_status.as_dict()
    return evolution


@router.get("/api/v0/sessions/{session_id}")
def get_session_detail(session_id: int, db: Session = Depends(get_db)) -> dict:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = planning_repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")

    linked_activity = next((activity for activity in session.activities if activity.sport_type == session.sport_type), None)
    recent_activity = _build_recent_activity(db, user=user, session=session)
    scheduled_sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=84)
    activities = execution_repo.get_activities(db, user.id, limit=120)
    recent_reality = build_recent_reality_window(
        today=get_local_now(user.timezone).date(),
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    active_facts = memory_repo.get_active_facts(db, user.id, limit=12)
    return build_session_detail(
        today_date=get_local_now(user.timezone).date(),
        session=session,
        linked_activity=execution_repo.to_pydantic_activity(linked_activity).model_dump() if linked_activity is not None else None,
        fitness=_build_today_fitness(db, user=user).model_dump(),
        recent_activity=recent_activity.model_dump() if recent_activity is not None else None,
        change_notes=[],
        watch_items=[],
        recent_reality=recent_reality.as_dict(),
        active_facts=[memory_repo.to_pydantic_fact(fact).model_dump() for fact in active_facts],
        surrounding_sessions=scheduled_sessions,
    )
