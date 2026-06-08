from __future__ import annotations

import unittest

from fitmas.legacy.domain.athlete.profile import build_athlete_profile
from fitmas.legacy.core import orm as s


class AthleteProfileTest(unittest.TestCase):
    def test_build_athlete_profile_assembles_current_user_state(self) -> None:
        user = s.User(
            id=7,
            name="Loic",
            objective="revenir fort",
            primary_objective="reprendre la course",
            weekly_structure_notes="Lundi piscine 7h. Jeudi matin dispo. Samedi sortie longue.",
            coaching_style="direct",
            coach_style="strict",
            coach_relationship="cadre net",
            coach_do="messages courts",
            coach_dont="pas de guilt",
            coach_soul="sobre",
            onboarding_status="completed",
        )
        user.sports = [
            s.UserSport(sport_type="running", priority_rank=0, level_note="intermediaire"),
            s.UserSport(sport_type="swimming", priority_rank=1, level_note="debutant"),
        ]
        user.constraints = [
            s.UserConstraint(text="mollet droit fragile"),
        ]
        user.preferences = [
            s.UserPreference(text="home trainer"),
            s.UserPreference(text="plutot le matin"),
        ]
        facts = [
            s.UserFact(category="availability", key="wednesday", value="Mercredi soir indispo", active=True),
            s.UserFact(category="goal", key="focus", value="Retrouver mon niveau running", active=True),
            s.UserFact(category="health", key="sleep", value="fatigue residuelle", active=True),
        ]

        profile = build_athlete_profile(user, facts=facts)

        self.assertEqual(profile.user_id, 7)
        self.assertEqual(profile.primary_sport, "running")
        self.assertEqual(profile.primary_sports, ("running", "swimming"))
        self.assertEqual(profile.level_by_sport["running"], "intermediate")
        self.assertEqual(profile.level_by_sport["swimming"], "beginner")
        self.assertIn("reprendre la course", profile.goals)
        self.assertIn("Retrouver mon niveau running", profile.goals)
        self.assertIn("monday", profile.weekly_availability)
        self.assertIn("thursday", profile.weekly_availability)
        self.assertIn("home_trainer", profile.equipment)
        self.assertIn("pool_access", profile.equipment)
        self.assertIn("morning", profile.preferred_training_times)
        self.assertTrue(profile.onboarding_completed)
        self.assertIn("running", profile.athlete_identity_summary)
        self.assertIn("strict", profile.coach_tone)


if __name__ == "__main__":
    unittest.main()
