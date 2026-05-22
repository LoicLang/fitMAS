from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas import schema as s
from fitmas.planning_contract import (
    AvailabilityConfidence,
    PlanConfidence,
    SessionRole,
    build_availability_state,
    build_planning_contract,
    build_session_policies,
    build_week_mission,
)


def _profile() -> AthleteProfileSnapshot:
    return AthleteProfileSnapshot(
        user_id=7,
        primary_sports=("running", "swimming"),
        primary_sport="running",
        level_by_sport={"running": "intermediate"},
        goals=("preparer un 10 km",),
        weekly_availability={
            "tuesday": ("Mardi soir dispo",),
            "thursday": ("Jeudi matin dispo",),
            "sunday": ("Dimanche sortie longue",),
        },
        equipment=("gps_watch", "home_trainer"),
        constraints=(),
        preferences=("matin",),
        preferred_training_times=("morning", "evening"),
        coach_tone="direct",
        coach_style_notes="court et clair",
        athlete_identity_summary="Loic s'entraine surtout en running.",
        onboarding_completed=True,
    )


def _session(
    *,
    session_id: int,
    day: str,
    label: str,
    scheduled_date: datetime,
    session_type: str,
    title: str,
    duration_min: int,
    intensity: str,
    load_score: int,
    priority: str,
    completion_status: str = "planned",
) -> s.ScheduledSession:
    return s.ScheduledSession(
        id=session_id,
        user_id=7,
        day=day,
        label=label,
        scheduled_date=scheduled_date,
        sport_type="running",
        session_type=session_type,
        session_title=title,
        session_goal="objectif",
        session_note="",
        session_description="",
        duration_min=duration_min,
        intensity=intensity,
        load_score=load_score,
        priority=priority,
        nutrition_focus="",
        flexibility="stable",
        completion_status=completion_status,
    )


class PlanningContractTest(unittest.TestCase):
    def test_build_availability_state_marks_profile_as_confirmed_when_week_is_known(self) -> None:
        state = build_availability_state(_profile())

        self.assertEqual(state.confidence, AvailabilityConfidence.CONFIRMED)
        self.assertEqual(len(state.preferred_windows), 3)
        self.assertIn("home_trainer", state.equipment)

    def test_build_session_policies_sets_role_and_confidence_from_dates_and_intensity(self) -> None:
        today = datetime(2026, 3, 24, 8, 0).date()
        sessions = [
            _session(
                session_id=1,
                day="tuesday",
                label="Mar",
                scheduled_date=datetime(2026, 3, 24, 18, 0),
                session_type="vo2",
                title="VO2 piste",
                duration_min=60,
                intensity="hard",
                load_score=5,
                priority="Cle",
            ),
            _session(
                session_id=2,
                day="monday",
                label="Lun",
                scheduled_date=datetime(2026, 4, 7, 18, 0),
                session_type="easy",
                title="Footing",
                duration_min=45,
                intensity="easy",
                load_score=1,
                priority="Normal",
            ),
        ]

        policies = build_session_policies(today=today, scheduled_sessions=sessions)

        self.assertEqual(policies[0].role, SessionRole.KEY)
        self.assertEqual(policies[0].confidence, PlanConfidence.COMMITTED)
        self.assertEqual(policies[1].confidence, PlanConfidence.PROJECTED)

    def test_build_week_mission_and_contract_surface_key_sessions_and_budget(self) -> None:
        today = datetime(2026, 3, 24, 8, 0).date()
        sessions = [
            _session(
                session_id=1,
                day="tuesday",
                label="Mar",
                scheduled_date=datetime(2026, 3, 24, 18, 0),
                session_type="vo2",
                title="VO2 piste",
                duration_min=60,
                intensity="hard",
                load_score=5,
                priority="Cle",
            ),
            _session(
                session_id=2,
                day="thursday",
                label="Jeu",
                scheduled_date=datetime(2026, 3, 26, 7, 0),
                session_type="easy",
                title="Footing facile",
                duration_min=45,
                intensity="easy",
                load_score=1,
                priority="Normal",
                completion_status="adapted",
            ),
        ]
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 240.0,
                "rationale": ("stabilite suffisante",),
            },
        )()

        policies = build_session_policies(today=today, scheduled_sessions=sessions)
        mission = build_week_mission(
            today=today,
            planning_decision=planning_decision,
            scheduled_sessions=sessions,
            session_policies=policies,
        )
        contract = build_planning_contract(
            today=today,
            profile=_profile(),
            week_plan=week_plan,
            planning_decision=planning_decision,
            scheduled_sessions=sessions,
        )

        self.assertEqual(len(mission.key_sessions), 1)
        self.assertIn("240", mission.success_criteria)
        self.assertEqual(contract.horizons[0].confidence, PlanConfidence.COMMITTED)
        self.assertEqual(contract.horizons[-1].confidence, PlanConfidence.PROJECTED)
        self.assertEqual(contract.change_budget.used, 1)


if __name__ == "__main__":
    unittest.main()
