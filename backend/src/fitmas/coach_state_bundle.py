from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.athlete_profile import AthleteProfileSnapshot, build_athlete_profile
from fitmas.calibration_status import CalibrationStatus, build_calibration_status
from fitmas.planning_contract import (
    AvailabilityState,
    PlanningContract,
    SessionPolicy,
    WeekMission,
    build_availability_state,
    build_planning_contract,
    build_session_policies,
    build_week_mission,
)
from fitmas.domain.execution.recent_reality import RecentRealityWindow, build_recent_reality_window
from fitmas.week_context import (
    build_deterministic_coach_reading,
    build_next_week_cadrage,
    build_planning_context,
    build_week_summary,
)


@dataclass(frozen=True, slots=True)
class CoachStateBundle:
    today_date: date
    active_memory: tuple[Any, ...]
    profile_snapshot: AthleteProfileSnapshot
    session_policies: tuple[SessionPolicy, ...]
    planning_contract: PlanningContract
    availability_state: AvailabilityState
    week_mission: WeekMission
    latest_adaptation: Any | None
    recent_adaptations: tuple[Any, ...]
    calibration_status: CalibrationStatus
    recent_reality: RecentRealityWindow
    week_summary: dict[str, Any]
    planning_context: dict[str, Any]
    next_week: dict[str, Any]
    coach_reading: str


def build_coach_state_bundle(
    db: Session,
    *,
    user: s.User,
    today_date: date,
    scheduled_sessions: list[s.ScheduledSession],
    activities: list[s.Activity],
    planning_decision: s.PlanningDecisionRecord | None,
    recent_adaptations_limit: int,
    week_plan: Any | None = None,
    readiness: Any | None = None,
    screen: str = "overview",
) -> CoachStateBundle:
    active_memory = tuple(
        repo.get_active_memory_items(
            db,
            user.id,
            profile_limit=24,
            working_limit=24,
            include_patterns=True,
            pattern_limit=6,
            total_limit=36,
        )
    )
    profile_snapshot = build_athlete_profile(user, facts=active_memory)
    session_policies = tuple(build_session_policies(today=today_date, scheduled_sessions=scheduled_sessions))
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
    recent_adaptations = tuple(repo.get_recent_adaptation_events(db, user.id, limit=recent_adaptations_limit))
    calibration_status = build_calibration_status(
        profile=profile_snapshot,
        memory_items=list(active_memory),
        activities=activities,
        adaptation_events=list(recent_adaptations),
        today=today_date,
    )
    recent_reality = build_recent_reality_window(
        today=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    mesocycle_week = int(_value(week_plan, "mesocycle_week") or 1)
    mesocycle_number = int(_value(week_plan, "mesocycle_number") or 1)
    is_deload = bool(_value(week_plan, "is_deload"))
    total_weeks = int(_value(week_plan, "total_weeks") or 1)
    week_summary = build_week_summary(
        today=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    planning_context = build_planning_context(
        planning_decision=planning_decision,
        mesocycle_week=mesocycle_week,
        mesocycle_number=mesocycle_number,
        is_deload=is_deload,
        total_weeks=total_weeks,
        readiness=readiness,
        recent_reality=recent_reality.as_dict(),
    )
    next_week = build_next_week_cadrage(
        current_mesocycle_week=mesocycle_week,
        current_planning_mode=str(getattr(planning_decision, "planning_mode", None) or "maintain_load"),
        current_target_tss=planning_context["target_tss"],
    )
    coach_reading = build_deterministic_coach_reading(
        week_summary=week_summary,
        planning_context=planning_context,
        next_week=next_week,
        screen=screen,
    )
    return CoachStateBundle(
        today_date=today_date,
        active_memory=active_memory,
        profile_snapshot=profile_snapshot,
        session_policies=session_policies,
        planning_contract=planning_contract,
        availability_state=availability_state,
        week_mission=week_mission,
        latest_adaptation=latest_adaptation,
        recent_adaptations=recent_adaptations,
        calibration_status=calibration_status,
        recent_reality=recent_reality,
        week_summary=week_summary,
        planning_context=planning_context,
        next_week=next_week,
        coach_reading=coach_reading,
    )


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
