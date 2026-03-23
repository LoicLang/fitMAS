from __future__ import annotations

import os
import tempfile
import unittest
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
        ):
            onboard = self.client.post("/api/v0/onboard", json=payload)
            self.assertEqual(onboard.status_code, 200)
            onboard_days = onboard.json()["week_plan"]["days"]
            self.assertEqual(len(onboard_days), 7)
            self.assertTrue(any(day["session_description"] for day in onboard_days if day["sport_type"] != "rest"))

            regenerate = self.client.post("/api/v0/week/regenerate")
            self.assertEqual(regenerate.status_code, 200)
            regenerate_days = regenerate.json()["days"]
            self.assertEqual(len(regenerate_days), 7)
            self.assertTrue(any(day["session_description"] for day in regenerate_days if day["sport_type"] != "rest"))


if __name__ == "__main__":
    unittest.main()
