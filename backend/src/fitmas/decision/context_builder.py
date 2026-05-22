from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

import fitmas.repository as repo
import fitmas.schema as s
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.core.time_context import build_time_context, get_local_now

from .context import (
    AthleteContext,
    CoachContext,
    ExecutionReality,
    LoadContext,
    LocalTimeContext,
    MemoryContext,
    PendingContext,
    PlanTimeline,
    ReadinessContext,
    WeeklyRealityDigest,
)
from .input_event import InputEvent


@dataclass(frozen=True, slots=True)
class ContextBuilderInput:
    event: InputEvent
    now: datetime | None = None
    screen: str = "decision_runtime"
    scheduled_sessions_limit: int = 84
    activities_limit: int = 500
    recent_adaptations_limit: int = 6


class DecisionContextUserNotFoundError(RuntimeError):
    pass


class DecisionContextBuilder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def build(self, request: ContextBuilderInput) -> CoachContext:
        user = self._db.get(s.User, request.event.user_id)
        if user is None:
            raise DecisionContextUserNotFoundError(f"user_id={request.event.user_id} not found")

        local_now = get_local_now(user.timezone, now=request.now)
        time_context = build_time_context(user.timezone, now=request.now)
        scheduled_sessions = tuple(
            repo.get_scheduled_sessions(
                self._db,
                user.id,
                limit=request.scheduled_sessions_limit,
            )
        )
        activities = tuple(repo.get_activities(self._db, user.id, limit=request.activities_limit))
        planning_decision = repo.get_latest_planning_decision_record(self._db, user.id)
        readiness_row = repo.get_latest_readiness_snapshot_record(self._db, user.id)
        readiness = repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
        coach_bundle = build_coach_state_bundle(
            self._db,
            user=user,
            today_date=local_now.date(),
            scheduled_sessions=list(scheduled_sessions),
            activities=list(activities),
            planning_decision=planning_decision,
            recent_adaptations_limit=request.recent_adaptations_limit,
            readiness=readiness,
            screen=request.screen,
        )

        return CoachContext(
            user=user,
            local_time=LocalTimeContext(
                timezone_name=user.timezone or "Europe/Paris",
                now_iso=local_now.isoformat(timespec="minutes"),
                today_iso=local_now.date().isoformat(),
                time_context=time_context,
            ),
            plan=PlanTimeline(
                scheduled_sessions=scheduled_sessions,
                session_policies=coach_bundle.session_policies,
                planning_contract=coach_bundle.planning_contract,
                week_mission=coach_bundle.week_mission,
                latest_adaptation=coach_bundle.latest_adaptation,
                recent_adaptations=coach_bundle.recent_adaptations,
            ),
            execution=ExecutionReality(
                activities=activities,
                recent_reality=coach_bundle.recent_reality,
                today_execution=None,
            ),
            memory=MemoryContext(active_memory=coach_bundle.active_memory, active_facts=()),
            athlete=AthleteContext(
                profile_snapshot=coach_bundle.profile_snapshot,
                calibration_status=coach_bundle.calibration_status,
            ),
            readiness=ReadinessContext(snapshot=readiness, state=None),
            load=LoadContext(summary=None, forecast=None),
            weekly_digest=WeeklyRealityDigest(
                week_summary=coach_bundle.week_summary,
                planning_context=coach_bundle.planning_context,
                next_week=coach_bundle.next_week,
                coach_reading=coach_bundle.coach_reading,
            ),
            pending=PendingContext(active_pending=None, summary=None),
        )
