from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.execution import repository as execution_repo
from fitmas.domain.memory import repository as memory_repo
from fitmas.domain.athlete.profile import AthleteProfileSnapshot, build_athlete_profile
from fitmas.domain.athlete.zones import AthleteZones, build_athlete_zones
from fitmas.domain.athlete.fitness_snapshot import FitnessSnapshot, build_fitness_snapshot
from fitmas.domain.planning import repository as planning_repo
from fitmas.domain.planning.planning_decision import PlanningDecision, build_planning_decision
from fitmas.domain.execution.recent_reality import build_recent_reality_window
from fitmas.domain.athlete.readiness import ReadinessState, build_readiness_state


@dataclass(frozen=True, slots=True)
class PlanningStateBundle:
    profile: AthleteProfileSnapshot
    fitness: FitnessSnapshot
    readiness: ReadinessState
    decision: PlanningDecision
    zones: AthleteZones


def assemble_planning_state(
    *,
    user: s.User,
    facts: Sequence[object],
    activities: Sequence[s.Activity],
    scheduled_sessions: Sequence[s.ScheduledSession],
    as_of_date: date | datetime | None = None,
    mesocycle_week: int = 1,
) -> PlanningStateBundle:
    profile = build_athlete_profile(user, facts=facts)
    zones = build_athlete_zones(profile, facts)
    fitness = build_fitness_snapshot(
        user_id=user.id,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        as_of_date=as_of_date,
    )
    recent_reality = build_recent_reality_window(
        today=fitness.date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )
    readiness = build_readiness_state(
        profile=profile,
        fitness=fitness,
        facts=facts,
        recent_reality=recent_reality,
    )
    decision = build_planning_decision(
        profile=profile,
        fitness=fitness,
        readiness=readiness,
        recent_reality=recent_reality,
        mesocycle_week=mesocycle_week,
    )
    return PlanningStateBundle(
        profile=profile,
        fitness=fitness,
        readiness=readiness,
        decision=decision,
        zones=zones,
    )


def refresh_planning_state(
    db: Session,
    *,
    user: s.User,
    as_of_date: date | datetime | None = None,
    mesocycle_week: int = 1,
) -> PlanningStateBundle:
    facts = memory_repo.get_active_memory_items(
        db,
        user.id,
        profile_limit=48,
        working_limit=48,
        include_patterns=True,
        pattern_limit=8,
        total_limit=72,
    )
    activities = execution_repo.get_activities(db, user.id, limit=500)
    scheduled_sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=84)
    bundle = assemble_planning_state(
        user=user,
        facts=facts,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        as_of_date=as_of_date,
        mesocycle_week=mesocycle_week,
    )
    athlete_repo.save_fitness_snapshot(db, bundle.fitness)
    athlete_repo.save_readiness_snapshot(db, bundle.readiness)
    planning_repo.save_planning_decision(db, bundle.decision)
    return bundle
