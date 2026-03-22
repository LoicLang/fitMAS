from __future__ import annotations

import unittest
from datetime import date

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.readiness import build_readiness_state


class ReadinessTest(unittest.TestCase):
    def test_build_readiness_state_flags_overload_and_pain(self) -> None:
        profile = AthleteProfileSnapshot(
            user_id=7,
            primary_sports=("running", "swimming"),
            primary_sport="running",
            level_by_sport={"running": "intermediate", "swimming": "beginner"},
            goals=("reprendre la course",),
            weekly_availability={"monday": ("Lundi matin",), "thursday": ("Jeudi matin",)},
            equipment=("gps_watch", "pool_access"),
            constraints=("mollet droit douloureux",),
            preferences=("plutot le matin",),
            preferred_training_times=("morning",),
            coach_tone="strict",
            coach_style_notes="cadre net",
            athlete_identity_summary="Loic s'entraine surtout en running.",
            onboarding_completed=True,
        )
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 3, 22),
            ctl=42.0,
            atl=61.0,
            tsb=-19.0,
            ramp_rate=0.22,
            weekly_target_tss=220.0,
            weekly_actual_tss=180.0,
            completion_rate_14d=0.35,
            key_sessions_done_14d=1,
            volume_sessions_done_14d=2,
            sport_ctl={"running": 30.0, "cycling": 0.0, "swimming": 12.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 3.5, "cycling": 0.0, "swimming": 1.2, "strength": 0.0, "climbing": 0.0},
        )
        facts = [
            {"category": "health", "value": "sommeil moyen et fatigue residuelle", "active": True},
            {"category": "availability", "value": "deplacement boulot mercredi soir", "active": True},
        ]

        readiness = build_readiness_state(profile=profile, fitness=fitness, facts=facts)

        self.assertEqual(readiness.physical, "low")
        self.assertEqual(readiness.mental, "low")
        self.assertEqual(readiness.logistical, "constrained")
        self.assertEqual(readiness.injury_risk, "high")
        self.assertIn("pain_reported", readiness.risk_flags)
        self.assertIn("high_fatigue_load", readiness.risk_flags)
        self.assertIn("ramp_rate_high", readiness.risk_flags)
        self.assertIn("travel_constraint", readiness.risk_flags)

    def test_build_readiness_state_detects_good_readiness(self) -> None:
        profile = AthleteProfileSnapshot(
            user_id=9,
            primary_sports=("running",),
            primary_sport="running",
            level_by_sport={"running": "intermediate"},
            goals=("progresser",),
            weekly_availability={"tuesday": ("Mardi matin",)},
            equipment=("gps_watch",),
            constraints=(),
            preferences=("dehors",),
            preferred_training_times=("morning",),
            coach_tone="supportive",
            coach_style_notes="encourageant",
            athlete_identity_summary="Athlete running regulier.",
            onboarding_completed=True,
        )
        fitness = FitnessSnapshot(
            user_id=9,
            date=date(2026, 3, 22),
            ctl=38.0,
            atl=30.0,
            tsb=8.0,
            ramp_rate=0.04,
            weekly_target_tss=170.0,
            weekly_actual_tss=140.0,
            completion_rate_14d=0.82,
            key_sessions_done_14d=2,
            volume_sessions_done_14d=4,
            sport_ctl={"running": 38.0, "cycling": 0.0, "swimming": 0.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 4.2, "cycling": 0.0, "swimming": 0.0, "strength": 0.0, "climbing": 0.0},
        )

        readiness = build_readiness_state(profile=profile, fitness=fitness, facts=[])

        self.assertEqual(readiness.physical, "high")
        self.assertEqual(readiness.mental, "high")
        self.assertEqual(readiness.logistical, "clear")
        self.assertEqual(readiness.injury_risk, "low")
        self.assertEqual(readiness.risk_flags, ())


if __name__ == "__main__":
    unittest.main()
