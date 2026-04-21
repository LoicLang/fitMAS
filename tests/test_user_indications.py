from __future__ import annotations

import unittest
from datetime import date, datetime

from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.user_indications import (
    IndicationTimeReference,
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
    build_availability_fact_payloads_from_indication,
    build_health_fact_payloads_from_indication,
    fallback_interpret_user_indication,
    parse_availability_fact_key,
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


class AvailabilityConstraintDurationTest(unittest.TestCase):
    """Chantier 4 : contraintes multi-jours → window_end_date + fact persistant."""

    def test_fallback_captures_two_weeks_duration(self) -> None:
        indication = fallback_interpret_user_indication(
            "Imprevu, je voyage pendant 2 semaines a partir de demain",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 19, 8, 0),
        )
        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 20))
        # 14 jours inclusifs : start + 13
        self.assertEqual(indication.time_reference.window_end_date, date(2026, 5, 3))

    def test_fallback_captures_fifteen_days_duration(self) -> None:
        indication = fallback_interpret_user_indication(
            "Imprevu, je suis absent 15 jours a partir de demain",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 19, 8, 0),
        )
        self.assertIsNotNone(indication)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 20))
        self.assertEqual(indication.time_reference.window_end_date, date(2026, 5, 4))

    def test_fallback_leaves_window_end_none_when_no_duration(self) -> None:
        indication = fallback_interpret_user_indication(
            "Je ne suis pas dispo demain soir",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )
        self.assertIsNotNone(indication)
        self.assertIsNotNone(indication.time_reference)
        self.assertIsNone(indication.time_reference.window_end_date)


class AvailabilityFactBuilderTest(unittest.TestCase):
    def _make(
        self,
        *,
        source_text: str,
        start: date,
        end: date,
        polarity: UserIndicationPolarity = UserIndicationPolarity.UNAVAILABLE,
    ) -> UserIndication:
        return UserIndication(
            kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
            confidence=0.9,
            source_text=source_text,
            scope=UserIndicationScope.WEEK,
            polarity=polarity,
            time_reference=IndicationTimeReference(
                label="window",
                resolved_date=start,
                day_key=None,
                relative_reference=None,
                window=None,
                window_end_date=end,
            ),
        )

    def test_builder_produces_fact_with_expires_at_anchored_on_window_end(self) -> None:
        indication = self._make(
            source_text="Je n'ai pas acces a la piscine pendant 2 semaines",
            start=date(2026, 4, 20),
            end=date(2026, 5, 3),
        )
        payloads = build_availability_fact_payloads_from_indication(indication)
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["category"], "availability")
        self.assertEqual(payload["key"], "unavailable_swimming_2026-04-20_2026-05-03")
        self.assertIn("piscine", payload["value"].lower())
        # expires_at ancré à J+1 minuit (le fact reste actif tout le dernier jour)
        self.assertEqual(payload["expires_at"], datetime(2026, 5, 4, 0, 0))

    def test_builder_fallbacks_to_general_when_no_activity_keyword(self) -> None:
        indication = self._make(
            source_text="Je suis indisponible pendant deux semaines",
            start=date(2026, 4, 20),
            end=date(2026, 5, 3),
        )
        payloads = build_availability_fact_payloads_from_indication(indication)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["key"], "unavailable_general_2026-04-20_2026-05-03")

    def test_builder_returns_nothing_for_single_day_constraint(self) -> None:
        indication = UserIndication(
            kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
            confidence=0.9,
            source_text="Je ne suis pas dispo demain",
            scope=UserIndicationScope.SINGLE_DAY,
            polarity=UserIndicationPolarity.UNAVAILABLE,
            time_reference=IndicationTimeReference(
                label="tomorrow",
                resolved_date=date(2026, 4, 20),
                day_key="monday",
                relative_reference="tomorrow",
                window=None,
                window_end_date=None,
            ),
        )
        self.assertEqual(build_availability_fact_payloads_from_indication(indication), [])

    def test_builder_returns_nothing_for_limited_polarity(self) -> None:
        indication = self._make(
            source_text="Je peux faire court pendant 2 semaines",
            start=date(2026, 4, 20),
            end=date(2026, 5, 3),
            polarity=UserIndicationPolarity.LIMITED,
        )
        self.assertEqual(build_availability_fact_payloads_from_indication(indication), [])

    def test_parse_key_roundtrip(self) -> None:
        parsed = parse_availability_fact_key("unavailable_swimming_2026-04-20_2026-05-03")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.sport_type, "swimming")
        self.assertEqual(parsed.start_date, date(2026, 4, 20))
        self.assertEqual(parsed.end_date, date(2026, 5, 3))

    def test_parse_key_returns_none_for_general_sport(self) -> None:
        parsed = parse_availability_fact_key("unavailable_general_2026-04-20_2026-05-03")
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed.sport_type)

    def test_parse_key_rejects_malformed(self) -> None:
        self.assertIsNone(parse_availability_fact_key("unavailable_x"))
        self.assertIsNone(parse_availability_fact_key(""))
        self.assertIsNone(parse_availability_fact_key(None))


if __name__ == "__main__":
    unittest.main()
