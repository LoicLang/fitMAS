from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.athlete_profile import AthleteProfileSnapshot, build_athlete_profile
from fitmas.athlete_zones import AthleteZones, build_athlete_zones
from fitmas.fitness_snapshot import FitnessSnapshot, build_fitness_snapshot
from fitmas.planning_decision import PlanningDecision, build_planning_decision
from fitmas.readiness import ReadinessState, build_readiness_state


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
    facts: Sequence[s.UserFact],
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
    readiness = build_readiness_state(profile=profile, fitness=fitness, facts=facts)
    decision = build_planning_decision(
        profile=profile,
        fitness=fitness,
        readiness=readiness,
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
    facts = repo.get_active_facts(db, user.id, limit=48)
    activities = repo.get_activities(db, user.id, limit=500)
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    bundle = assemble_planning_state(
        user=user,
        facts=facts,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        as_of_date=as_of_date,
        mesocycle_week=mesocycle_week,
    )
    repo.save_fitness_snapshot(db, bundle.fitness)
    repo.save_readiness_snapshot(db, bundle.readiness)
    repo.save_planning_decision(db, bundle.decision)
    return bundle
