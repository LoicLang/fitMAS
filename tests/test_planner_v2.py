from __future__ import annotations

import unittest
from datetime import date

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.planner import build_week_plan
from fitmas.planning_decision import PlanningDecision


class PlannerV2Test(unittest.TestCase):
    def test_build_week_plan_exposes_planning_context_and_actionable_descriptions(self) -> None:
        decision = _decision(planning_mode="maintain_load", key_session_count=2, long_session=True, weekly_target_tss=260.0)
        profile = _profile()

        week = build_week_plan(
            sports=["running", "swimming", "strength"],
            weekly_structure_notes="Mercredi fragile, sortie longue dimanche.",
            constraints=["Lundi boulot tard"],
            coach_name="FitMAS",
            planning_decision=decision,
            athlete_profile=profile,
        )

        self.assertEqual(week["planning_context"]["planning_mode"], "maintain_load")
        active_days = [day for day in week["days"] if day["sport_type"] != "rest"]
        self.assertTrue(active_days)
        self.assertTrue(all(day["session_description"] or day["sport_type"] == "rest" for day in week["days"]))
        self.assertTrue(any(day["sport_type"] == "running" for day in active_days))

    def test_injury_protection_week_stays_protective(self) -> None:
        decision = _decision(planning_mode="injury_protection", key_session_count=0, long_session=False, weekly_target_tss=120.0)

        week = build_week_plan(
            sports=["running", "strength"],
            weekly_structure_notes="Semaine de reprise douce.",
            constraints=["Douleur tendon"],
            coach_name="FitMAS",
            planning_decision=decision,
        )

        active_days = [day for day in week["days"] if day["sport_type"] != "rest"]
        self.assertTrue(active_days)
        self.assertTrue(all(day["intensity"] == "easy" for day in active_days))
        self.assertTrue(all(day["load_score"] <= 1 for day in active_days))


def _decision(*, planning_mode: str, key_session_count: int, long_session: bool, weekly_target_tss: float) -> PlanningDecision:
    return PlanningDecision(
        user_id=1,
        week_start=date(2026, 3, 23),
        decision_version="v1",
        planning_mode=planning_mode,
        adaptation_level="low",
        adaptation_scope="week",
        weekly_target_tss=weekly_target_tss,
        intensity_distribution="balanced",
        key_session_count=key_session_count,
        strength_session_count=1,
        long_session=long_session,
        rationale=("test rationale",),
        adaptations=("test adaptation",),
        risk_flags=(),
    )


def _profile() -> AthleteProfileSnapshot:
    return AthleteProfileSnapshot(
        user_id=1,
        primary_sports=("running", "swimming", "strength"),
        primary_sport="running",
        level_by_sport={"running": "intermediate", "swimming": "intermediate", "strength": "unknown"},
        goals=("reprendre propre",),
        weekly_availability={"wednesday": ("matin",), "sunday": ("long",)},
        equipment=("pool_access",),
        constraints=("travail dense",),
        preferences=("natation le matin",),
        preferred_training_times=("morning",),
        coach_tone="direct",
        coach_style_notes="direct",
        athlete_identity_summary="Loic reprend proprement.",
        onboarding_completed=True,
    )


if __name__ == "__main__":
    unittest.main()
