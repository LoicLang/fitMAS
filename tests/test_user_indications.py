from __future__ import annotations

import unittest
from datetime import date, datetime

from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.user_indications import (
    UserIndicationKind,
    build_health_fact_payloads_from_indication,
    fallback_interpret_user_indication,
)


class UserIndicationsTest(unittest.TestCase):
    def test_fallback_interprets_future_availability_constraint(self) -> None:
        indication = fallback_interpret_user_indication(
            "Je ne suis pas dispo demain soir",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 3, 30))
        self.assertEqual(indication.time_reference.window, "evening")

    def test_fallback_interprets_health_signal_and_builds_fact(self) -> None:
        indication = fallback_interpret_user_indication(
            "J'ai mal a l'epaule quand je nage, ca tire",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.HEALTH_SIGNAL)
        self.assertEqual(indication.body_zone, "shoulder")
        self.assertEqual(indication.trigger_activity, "swimming")

        payloads = build_health_fact_payloads_from_indication(indication)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["category"], "health")
        self.assertIn("shoulder", payloads[0]["key"])
        self.assertIn("Douleur", payloads[0]["value"])

    def test_fallback_interprets_general_illness_and_clarification_answer(self) -> None:
        indication = fallback_interpret_user_indication(
            "Je suis malade comme un chien j'ai rien fait",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 1, 8, 0),
            recent_agent_text="Je ne vois pas de trace de ton renfo hier. Tu l'as faite ou non ?",
            clarification_date=date(2026, 3, 31),
            clarification_sport_type="strength",
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.HEALTH_SIGNAL)
        self.assertEqual(indication.symptom_type, "illness")
        self.assertFalse(indication.execution_completed)
        self.assertEqual(indication.execution_sport_type, "strength")
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 3, 31))

    def test_fallback_interprets_week_travel_constraint(self) -> None:
        indication = fallback_interpret_user_indication(
            "Cette semaine je voyage de mercredi a vendredi",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertEqual(indication.scope.value, "week")
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 1))

    def test_resolve_planning_window_matches_single_future_session(self) -> None:
        indication = fallback_interpret_user_indication(
            "Je ne suis pas dispo demain soir",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )
        self.assertIsNotNone(indication)

        resolution = resolve_planning_window(
            indication=indication,
            scheduled_sessions=[
                {
                    "id": 12,
                    "day": "monday",
                    "scheduled_date": datetime(2026, 3, 30, 18, 0),
                    "sport_type": "running",
                    "session_title": "Tempo",
                    "completion_status": "planned",
                    "priority": "Seance cle",
                }
            ],
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(resolution)
        self.assertTrue(resolution.exact_match)
        self.assertEqual(resolution.matched_session_id, 12)


if __name__ == "__main__":
    unittest.main()
