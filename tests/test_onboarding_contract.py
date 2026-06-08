from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-onboarding-contract-", suffix=".db"))

from fastapi.testclient import TestClient

from fitmas.legacy.api import app
from fitmas.legacy.app.api.payloads import OnboardPreviewPayload
from fitmas.legacy.app.api.support import build_onboarding_facts, normalized_onboarding_payload


class OnboardingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_normalized_payload_derives_coach_profile_and_goal_summary(self) -> None:
        payload = OnboardPreviewPayload(
            name="Loic",
            primary_objective="revenir fort en course",
            goal_context="trail de 25 km dans 8 semaines",
            sports=["course", "velo"],
            weekly_structure_notes="mardi fragile; dimanche sortie longue",
            current_state_notes="reprise prudente, jambes lourdes depuis une semaine",
            constraints=["mardi soir fragile"],
            preferences=["matin > soir", "trail > route"],
            coach_name="Aster",
            coach_preset="protecteur",
            coach_do="proteger la regularite",
            coach_dont="culpabiliser",
        )

        normalized = normalized_onboarding_payload(payload)

        self.assertEqual(normalized["coach_preset"], "protective")
        self.assertEqual(normalized["coach_name"], "Aster")
        self.assertEqual(normalized["coach_style"], "protective")
        self.assertIn("trail de 25 km", normalized["goal_summary"])
        self.assertEqual(normalized["preferences"], ["matin > soir", "trail > route"])

    def test_build_onboarding_facts_adds_goal_availability_and_training_state(self) -> None:
        payload = normalized_onboarding_payload(
            OnboardPreviewPayload(
                name="Loic",
                primary_objective="reprendre proprement",
                goal_context="sans course cible",
                sports=["course"],
                weekly_structure_notes="mardi fragile, dimanche long",
                current_state_notes="fatigue legere, reprise recente",
                constraints=["mardi fragile"],
                preferences=["matin > soir"],
                coach_name="FitMAS",
                coach_preset="direct",
            )
        )

        facts = build_onboarding_facts(payload)
        categories = {(fact["category"], fact["key"]) for fact in facts}

        self.assertIn(("goal", "primary_goal"), categories)
        self.assertIn(("availability", "weekly_structure"), categories)
        self.assertIn(("training_state", "current_state"), categories)
        self.assertIn(("coaching", "coach_style_preference"), categories)

    def test_preview_endpoint_returns_setup_preview(self) -> None:
        payload = {
            "name": "Loic",
            "primary_objective": "reprendre en course",
            "goal_context": "10 km dans 6 semaines",
            "sports": ["course", "natation"],
            "weekly_structure_notes": "mardi fragile, dimanche sortie longue",
            "current_state_notes": "reprise, fatigue faible",
            "constraints": ["mardi soir fragile"],
            "preferences": ["natation le matin"],
            "coach_name": "FitMAS",
            "coach_preset": "calme",
            "coach_do": "recadrer vite",
            "coach_dont": "parler pour rien",
        }

        with (
            patch("fitmas.legacy.app.api.routes_onboarding.formulate_onboarding_recap", return_value="recap"),
            patch("fitmas.legacy.app.api.routes_onboarding.preview_coach_voice", return_value=["a", "b", "c"]),
        ):
            response = self.client.post("/api/v0/onboard/preview", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["coach_preview"], ["a", "b", "c"])
        self.assertEqual(data["recap"], "recap")
        self.assertEqual(data["calibration_status"]["phase"], "draft")
        self.assertTrue(any(line.startswith("Cap:") for line in data["setup_preview"]))
        self.assertTrue(any(line.startswith("Coach:") for line in data["setup_preview"]))


if __name__ == "__main__":
    unittest.main()
