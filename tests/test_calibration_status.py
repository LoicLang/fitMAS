from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from fitmas import schema as s
from fitmas.athlete_profile import build_athlete_profile
from fitmas.calibration_status import build_calibration_status, build_initial_calibration_status


class CalibrationStatusTest(unittest.TestCase):
    def test_build_initial_calibration_status_starts_in_draft(self) -> None:
        status = build_initial_calibration_status(
            {
                "primary_objective": "reprendre en course",
                "goal_context": "",
                "preferences": [],
                "current_state_notes": "",
            }
        )

        self.assertEqual(status.phase.value, "draft")
        self.assertTrue(status.known_unknowns)

    def test_build_calibration_status_becomes_stable_when_real_usage_exists(self) -> None:
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
        user.sports = [s.UserSport(sport_type="running", priority_rank=0, level_note="intermediaire")]
        user.constraints = [s.UserConstraint(text="mardi soir fragile")]
        user.preferences = [s.UserPreference(text="plutot le matin")]

        now = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        facts = [
            s.UserFact(
                user_id=7,
                category="availability",
                key="weekly_structure",
                value="Lundi piscine 7h. Jeudi matin dispo. Samedi sortie longue.",
                source="onboarding",
                active=True,
                confirmed=True,
                confidence=1.0,
                created_at=(now - timedelta(days=21)).replace(tzinfo=None),
            ),
            s.UserFact(
                user_id=7,
                category="training_state",
                key="current_state",
                value="bloc relance, fatigue faible",
                source="onboarding",
                active=True,
                confirmed=True,
                confidence=0.9,
                created_at=(now - timedelta(days=21)).replace(tzinfo=None),
            ),
            s.UserPattern(
                user_id=7,
                category="availability",
                pattern_type="recurring_unavailable_slot",
                key="mardi_soir",
                value="Mardi soir souvent impossible",
                source="maintenance",
                active=True,
                confirmed=True,
                confidence=0.82,
                evidence_count=4,
                created_at=(now - timedelta(days=8)).replace(tzinfo=None),
            ),
        ]
        profile = build_athlete_profile(user, facts=facts)
        activities = [
            s.Activity(user_id=7, title="Run", sport_type="running", created_at=(now - timedelta(days=2)).replace(tzinfo=None)),
            s.Activity(user_id=7, title="Run", sport_type="running", created_at=(now - timedelta(days=4)).replace(tzinfo=None)),
            s.Activity(user_id=7, title="Run", sport_type="running", created_at=(now - timedelta(days=6)).replace(tzinfo=None)),
            s.Activity(user_id=7, title="Run", sport_type="running", created_at=(now - timedelta(days=8)).replace(tzinfo=None)),
            s.Activity(user_id=7, title="Run", sport_type="running", created_at=(now - timedelta(days=10)).replace(tzinfo=None)),
        ]
        adaptations = [
            {
                "created_at": (now - timedelta(days=3)).isoformat(),
            }
        ]

        status = build_calibration_status(
            profile=profile,
            memory_items=facts,
            activities=activities,
            adaptation_events=adaptations,
            today=now.date(),
        )

        self.assertEqual(status.phase.value, "stable")
        self.assertEqual(status.pattern_count, 1)
        self.assertGreaterEqual(status.activity_count_14d, 5)


if __name__ == "__main__":
    unittest.main()
