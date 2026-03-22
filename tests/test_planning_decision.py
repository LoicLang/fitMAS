from __future__ import annotations

import unittest
from datetime import date

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.planning_decision import build_planning_decision
from fitmas.readiness import ReadinessState


def _profile() -> AthleteProfileSnapshot:
    return AthleteProfileSnapshot(
        user_id=7,
        primary_sports=("running", "swimming"),
        primary_sport="running",
        level_by_sport={"running": "intermediate", "swimming": "beginner"},
        goals=("reprendre la course",),
        weekly_availability={"monday": ("Lundi matin",), "thursday": ("Jeudi matin",)},
        equipment=("gps_watch", "pool_access"),
        constraints=(),
        preferences=("matin",),
        preferred_training_times=("morning",),
        coach_tone="strict",
        coach_style_notes="cadre net",
        athlete_identity_summary="Loic s'entraine surtout en running.",
        onboarding_completed=True,
    )


class PlanningDecisionTest(unittest.TestCase):
    def test_build_planning_decision_protects_injury_first(self) -> None:
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 3, 22),
            ctl=40.0,
            atl=58.0,
            tsb=-18.0,
            ramp_rate=0.18,
            weekly_target_tss=220.0,
            weekly_actual_tss=180.0,
            completion_rate_14d=0.42,
            key_sessions_done_14d=1,
            volume_sessions_done_14d=2,
            sport_ctl={"running": 30.0, "cycling": 0.0, "swimming": 10.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 3.2, "cycling": 0.0, "swimming": 1.0, "strength": 0.0, "climbing": 0.0},
        )
        readiness = ReadinessState(
            user_id=7,
            date=date(2026, 3, 22),
            physical="low",
            mental="medium",
            logistical="clear",
            injury_risk="high",
            risk_flags=("pain_reported", "high_fatigue_load", "ramp_rate_high"),
            summary="Physique low.",
        )

        decision = build_planning_decision(profile=_profile(), fitness=fitness, readiness=readiness)

        self.assertEqual(decision.planning_mode, "injury_protection")
        self.assertEqual(decision.key_session_count, 0)
        self.assertFalse(decision.long_session)
        self.assertLess(decision.weekly_target_tss, fitness.weekly_target_tss)
        self.assertIn("pain_reported", decision.risk_flags)

    def test_build_planning_decision_increases_load_when_readiness_is_high(self) -> None:
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 3, 22),
            ctl=42.0,
            atl=31.0,
            tsb=11.0,
            ramp_rate=0.03,
            weekly_target_tss=240.0,
            weekly_actual_tss=230.0,
            completion_rate_14d=0.82,
            key_sessions_done_14d=2,
            volume_sessions_done_14d=4,
            sport_ctl={"running": 42.0, "cycling": 0.0, "swimming": 10.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 4.5, "cycling": 0.0, "swimming": 1.0, "strength": 0.0, "climbing": 0.0},
        )
        readiness = ReadinessState(
            user_id=7,
            date=date(2026, 3, 22),
            physical="high",
            mental="high",
            logistical="clear",
            injury_risk="low",
            risk_flags=(),
            summary="Stable.",
        )

        decision = build_planning_decision(profile=_profile(), fitness=fitness, readiness=readiness, mesocycle_week=2)

        self.assertEqual(decision.planning_mode, "increase_load")
        self.assertEqual(decision.adaptation_level, "low")
        self.assertGreater(decision.weekly_target_tss, fitness.weekly_target_tss)
        self.assertTrue(decision.long_session)
        self.assertGreaterEqual(decision.key_session_count, 2)

    def test_build_planning_decision_deloads_on_week_four(self) -> None:
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 3, 22),
            ctl=44.0,
            atl=44.0,
            tsb=0.0,
            ramp_rate=0.02,
            weekly_target_tss=260.0,
            weekly_actual_tss=240.0,
            completion_rate_14d=0.71,
            key_sessions_done_14d=2,
            volume_sessions_done_14d=3,
            sport_ctl={"running": 44.0, "cycling": 0.0, "swimming": 12.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 4.8, "cycling": 0.0, "swimming": 1.1, "strength": 0.0, "climbing": 0.0},
        )
        readiness = ReadinessState(
            user_id=7,
            date=date(2026, 3, 22),
            physical="medium",
            mental="medium",
            logistical="clear",
            injury_risk="low",
            risk_flags=(),
            summary="Stable.",
        )

        decision = build_planning_decision(profile=_profile(), fitness=fitness, readiness=readiness, mesocycle_week=4)

        self.assertEqual(decision.planning_mode, "deload")
        self.assertEqual(decision.intensity_distribution, "recovery")
        self.assertLess(decision.weekly_target_tss, fitness.weekly_target_tss)
        self.assertFalse(decision.long_session)


if __name__ == "__main__":
    unittest.main()
