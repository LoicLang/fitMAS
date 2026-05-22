from __future__ import annotations

import unittest
from datetime import date

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas.domain.athlete.fitness_snapshot import FitnessSnapshot
from fitmas.planning_decision import build_planning_decision
from fitmas.domain.execution.recent_reality import RecentRealityWindow
from fitmas.domain.athlete.readiness import ReadinessState, build_readiness_state


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

    def test_planning_decision_does_not_enter_injury_mode_from_stale_textual_memory(self) -> None:
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 5, 11),
            ctl=10.8,
            atl=12.0,
            tsb=-1.2,
            ramp_rate=0.02,
            weekly_target_tss=94.1,
            weekly_actual_tss=90.0,
            completion_rate_14d=0.75,
            key_sessions_done_14d=2,
            volume_sessions_done_14d=4,
            sport_ctl={"running": 10.8, "cycling": 0.0, "swimming": 0.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 2.4, "cycling": 0.0, "swimming": 0.0, "strength": 0.0, "climbing": 0.0},
        )
        profile = _profile()
        noisy_facts = [
            {
                "category": "coaching",
                "key": "sleep_note",
                "value": "Douche froide interessante pour le sommeil",
                "active": True,
                "status": "open",
                "affects": ["conversation"],
            },
            {
                "category": "health",
                "key": "old_tendon",
                "value": "Ancienne tension tendon reglee",
                "active": True,
                "status": "resolved",
                "signal_kind": "tension",
                "severity": "mild",
                "affects": ["readiness"],
            },
            {
                "category": "pattern",
                "key": "work_intense",
                "value": "Travail IA intensif",
                "active": True,
                "status": "open",
                "affects": ["planning"],
            },
        ]

        readiness = build_readiness_state(profile=profile, fitness=fitness, facts=noisy_facts)
        decision = build_planning_decision(
            profile=profile,
            fitness=fitness,
            readiness=readiness,
            mesocycle_week=1,
        )

        self.assertNotEqual(decision.planning_mode, "injury_protection")
        self.assertNotIn("pain_reported", decision.risk_flags)
        self.assertNotIn("sleep_risk", decision.risk_flags)
        self.assertNotIn("travel_constraint", decision.risk_flags)
        self.assertGreaterEqual(decision.weekly_target_tss, 90.0)

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

    def test_build_planning_decision_restarts_when_recent_reality_is_too_low(self) -> None:
        fitness = FitnessSnapshot(
            user_id=7,
            date=date(2026, 3, 30),
            ctl=40.0,
            atl=36.0,
            tsb=4.0,
            ramp_rate=-0.12,
            weekly_target_tss=280.0,
            weekly_actual_tss=110.0,
            completion_rate_14d=0.45,
            key_sessions_done_14d=1,
            volume_sessions_done_14d=1,
            sport_ctl={"running": 40.0, "cycling": 0.0, "swimming": 8.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 2.0, "cycling": 0.0, "swimming": 0.8, "strength": 0.0, "climbing": 0.0},
        )
        readiness = ReadinessState(
            user_id=7,
            date=date(2026, 3, 30),
            physical="medium",
            mental="medium",
            logistical="clear",
            injury_risk="low",
            risk_flags=("low_recent_completion", "load_under_target", "consistency_streak_broken"),
            summary="Relance necessaire.",
        )
        recent_reality = RecentRealityWindow(
            planned_sessions_7d=4,
            confirmed_sessions_7d=1,
            claimed_sessions_7d=0,
            key_sessions_salvaged_7d=1,
            planned_tss_7d=250.0,
            observed_tss_7d=110.0,
            compliance_confirmed=0.25,
            load_ratio=0.44,
            missed_streak_days=2,
        )

        decision = build_planning_decision(
            profile=_profile(),
            fitness=fitness,
            readiness=readiness,
            recent_reality=recent_reality,
            mesocycle_week=2,
        )

        self.assertEqual(decision.planning_mode, "restart_consistency")
        self.assertEqual(decision.adaptation_level, "medium")
        self.assertLess(decision.weekly_target_tss, fitness.weekly_target_tss)
        self.assertEqual(decision.key_session_count, 1)
        self.assertFalse(decision.long_session)


if __name__ == "__main__":
    unittest.main()
