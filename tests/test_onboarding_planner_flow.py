from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-onboarding-tests-", suffix=".db"))

from fastapi.testclient import TestClient

from fitmas.api import app
import fitmas.api_onboarding as api_onboarding
from fitmas.db import Base, engine, init_db


class OnboardingPlannerFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        engine.dispose()

    def test_onboard_and_regenerate_use_planner_v2_flow(self) -> None:
        payload = {
            "name": "Loic",
            "age": 31,
            "objective": "reprendre en course",
            "coaching_style": "direct",
            "sports": ["course", "natation"],
            "constraints": ["mercredi fragile", "dimanche sortie longue"],
            "preferences": ["natation le matin"],
            "primary_objective": "retrouver mon niveau en running",
            "weekly_structure_notes": "Mercredi fragile, dimanche sortie longue, boulot tard lundi.",
            "timezone": "Europe/Paris",
            "coach_name": "FitMAS",
            "coach_style": "direct",
            "coach_relationship": "coach exigeant",
            "coach_do": "dire les choses clairement",
            "coach_dont": "parler pour rien",
            "coach_soul": "calme et precis",
        }

        with (
            patch.object(api_onboarding, "formulate_onboarding_recap", return_value="recap"),
            patch.object(api_onboarding, "formulate_week_plan", side_effect=lambda planner_output, user_profile, coach_profile, time_context=None: {
                "intention": planner_output["intention_seed"],
                "summary": "summary",
                "days": planner_output["days"],
            }),
            patch.object(
                api_onboarding,
                "guard_generated_week_coherence",
                side_effect=lambda enriched_week, **_kwargs: SimpleNamespace(week=enriched_week, used_fallback=False),
            ) as guard_week,
        ):
            onboard = self.client.post("/api/v0/onboard", json=payload)
            self.assertEqual(onboard.status_code, 200)
            self.assertEqual(onboard.json()["calibration_status"]["phase"], "draft")
            onboard_week = onboard.json()["week_plan"]
            onboard_days = onboard_week["days"]
            self.assertEqual(len(onboard_days), 7)
            self.assertTrue(any(day["session_description"] for day in onboard_days if day["sport_type"] != "rest"))
            self.assertEqual(onboard_week["total_weeks"], 1)
            self.assertEqual(onboard_week["mesocycle_week"], 1)
            self.assertFalse(onboard_week["is_deload"])
            self.assertIn("Semaine 1/4", onboard_week["week_label"])

            regenerate = self.client.post("/api/v0/week/regenerate")
            self.assertEqual(regenerate.status_code, 200)
            regenerate_week = regenerate.json()
            regenerate_days = regenerate_week["days"]
            self.assertEqual(len(regenerate_days), 7)
            self.assertTrue(any(day["session_description"] for day in regenerate_days if day["sport_type"] != "rest"))
            self.assertEqual(regenerate_week["total_weeks"], 2)
            self.assertEqual(regenerate_week["mesocycle_week"], 2)
            self.assertFalse(regenerate_week["is_deload"])
            self.assertEqual(regenerate_week["cycle_length"], 4)

            second_regenerate = self.client.post("/api/v0/week/regenerate")
            self.assertEqual(second_regenerate.status_code, 200)
            self.assertEqual(second_regenerate.json()["total_weeks"], 3)
            self.assertEqual(second_regenerate.json()["mesocycle_week"], 3)

            third_regenerate = self.client.post("/api/v0/week/regenerate")
            self.assertEqual(third_regenerate.status_code, 200)
            self.assertEqual(third_regenerate.json()["total_weeks"], 4)
            self.assertEqual(third_regenerate.json()["mesocycle_week"], 4)
            self.assertTrue(third_regenerate.json()["is_deload"])
            self.assertIn("Recuperation", third_regenerate.json()["week_label"])
            self.assertEqual(guard_week.call_count, 4)


if __name__ == "__main__":
    unittest.main()
