from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch

import fitmas.calibration_llm as calibration_llm
import fitmas.user_indication_llm as user_indication_llm
from fitmas import calibration_needs
from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.user_indications import (
    IndicationTimeReference,
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
    build_availability_fact_payloads_from_indication,
    build_health_fact_payloads_from_indication,
    indication_from_payload,
    parse_availability_fact_key,
)


class UserIndicationsTest(unittest.TestCase):
    def test_structured_payload_builds_future_availability_constraint(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "availability_constraint",
                "confidence": 0.9,
                "scope": "single_window",
                "polarity": "unavailable",
                "time_reference": {
                    "label": "demain soir",
                    "resolved_date": "2026-03-30",
                    "day_key": "monday",
                    "relative_reference": "tomorrow",
                    "window": "evening",
                },
            },
            source_text="Je ne suis pas dispo demain soir",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 3, 30))
        self.assertEqual(indication.time_reference.window, "evening")

    def test_structured_payload_builds_health_signal_and_fact(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "health_signal",
                "confidence": 0.92,
                "scope": "single_day",
                "polarity": "signal",
                "time_reference": {"label": "today", "resolved_date": "2026-03-29"},
                "health": {
                    "body_zone": "shoulder",
                    "trigger_activity": "swimming",
                    "symptom_type": "pain_tightness",
                    "severity": "moderate",
                },
            },
            source_text="J'ai mal a l'epaule quand je nage, ca tire",
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

    def test_llm_interpreter_does_not_promote_keyword_fallback_when_model_says_none(self) -> None:
        prompts: list[str] = []

        def fake_request_json(*, prompt, **kwargs):
            prompts.append(prompt)
            return {
                "kind": "none",
                "confidence": 0.9,
                "scope": "unknown",
                "polarity": None,
                "time_reference": None,
                "health": None,
                "execution": None,
                "followup_needed": False,
                "followup_reason": None,
            }

        with patch("fitmas.user_indication_llm.gw.client", return_value=object()):
            with patch(
                "fitmas.user_indication_llm.gw.request_json",
                side_effect=fake_request_json,
            ):
                indication = user_indication_llm.interpret_user_indication(
                    "top pas de douleur",
                    timezone_name="Europe/Paris",
                    now=datetime(2026, 3, 29, 8, 0),
                )

        self.assertIsNone(indication)
        self.assertNotIn("Signal lexical non conclusif", prompts[0])
        self.assertNotIn("Verifie negation", prompts[0])
        self.assertIn("Retourne UNIQUEMENT un JSON", prompts[0])

    def test_calibration_resolution_does_not_use_keyword_fallback_without_llm(self) -> None:
        need = calibration_needs.CalibrationNeed(
            id="availability_window:availability:sunday",
            need_type=calibration_needs.CalibrationNeedType.AVAILABILITY_WINDOW,
            topic="availability:sunday",
            status=calibration_needs.CalibrationNeedStatus.OPEN,
            why_now="test",
            priority=calibration_needs.CalibrationNeedPriority.MEDIUM,
            source="test",
            channel_hint="telegram",
            context={"day": "sunday", "day_label": "dimanche"},
            allowed_answers=("morning", "evening", "both", "none"),
            write_targets=("working_memory.availability",),
        )

        with patch("fitmas.calibration_llm.gw.client", return_value=None):
            resolution = calibration_llm.extract_calibration_resolution(
                user_text="Plutot le soir",
                need=need,
                timezone_name="Europe/Paris",
            )

        self.assertIsNone(resolution)

    def test_structured_payload_can_carry_health_and_execution_update(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "health_signal",
                "confidence": 0.95,
                "scope": "single_day",
                "polarity": "signal",
                "time_reference": {
                    "label": "clarification",
                    "resolved_date": "2026-03-31",
                    "day_key": "tuesday",
                    "relative_reference": "yesterday",
                },
                "health": {
                    "body_zone": "general",
                    "trigger_activity": "general",
                    "symptom_type": "illness",
                    "severity": "moderate",
                },
                "execution": {
                    "sport_type": "strength",
                    "status": "not_done",
                },
            },
            source_text="Je suis malade comme un chien j'ai rien fait",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 1, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.HEALTH_SIGNAL)
        self.assertEqual(indication.symptom_type, "illness")
        self.assertFalse(indication.execution_completed)
        self.assertEqual(indication.execution_sport_type, "strength")
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 3, 31))

    def test_structured_payload_builds_week_travel_constraint(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "availability_constraint",
                "confidence": 0.95,
                "scope": "week",
                "polarity": "unavailable",
                "time_reference": {
                    "label": "mercredi a vendredi",
                    "resolved_date": "2026-04-01",
                    "day_key": "wednesday",
                    "relative_reference": "this_week",
                    "window_end_date": "2026-04-03",
                },
            },
            source_text="Cette semaine je voyage de mercredi a vendredi",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertEqual(indication.scope.value, "week")
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 1))

    def test_resolve_planning_window_matches_single_future_session(self) -> None:
        indication = UserIndication(
            kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
            confidence=0.9,
            source_text="Je ne suis pas dispo demain soir",
            scope=UserIndicationScope.SINGLE_WINDOW,
            polarity=UserIndicationPolarity.UNAVAILABLE,
            time_reference=IndicationTimeReference(
                label="demain soir",
                resolved_date=date(2026, 3, 30),
                day_key="monday",
                relative_reference="tomorrow",
                window="evening",
            ),
        )

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
    """Chantier 4 now trusts the LLM-provided window_end_date."""

    def test_structured_payload_carries_two_weeks_window_end(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "availability_constraint",
                "confidence": 0.9,
                "scope": "week",
                "polarity": "unavailable",
                "time_reference": {
                    "label": "2 semaines a partir de demain",
                    "resolved_date": "2026-04-20",
                    "relative_reference": "tomorrow",
                    "window_end_date": "2026-05-03",
                },
            },
            source_text="Imprevu, je voyage pendant 2 semaines a partir de demain",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 19, 8, 0),
        )
        self.assertIsNotNone(indication)
        self.assertEqual(indication.kind, UserIndicationKind.AVAILABILITY_CONSTRAINT)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 20))
        self.assertEqual(indication.time_reference.window_end_date, date(2026, 5, 3))

    def test_structured_payload_carries_fifteen_days_window_end(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "availability_constraint",
                "confidence": 0.9,
                "scope": "week",
                "polarity": "unavailable",
                "time_reference": {
                    "label": "15 jours a partir de demain",
                    "resolved_date": "2026-04-20",
                    "relative_reference": "tomorrow",
                    "window_end_date": "2026-05-04",
                },
            },
            source_text="Imprevu, je suis absent 15 jours a partir de demain",
            timezone_name="Europe/Paris",
            now=datetime(2026, 4, 19, 8, 0),
        )
        self.assertIsNotNone(indication)
        self.assertIsNotNone(indication.time_reference)
        self.assertEqual(indication.time_reference.resolved_date, date(2026, 4, 20))
        self.assertEqual(indication.time_reference.window_end_date, date(2026, 5, 4))

    def test_structured_payload_leaves_window_end_none_when_absent(self) -> None:
        indication = indication_from_payload(
            {
                "kind": "availability_constraint",
                "confidence": 0.9,
                "scope": "single_window",
                "polarity": "unavailable",
                "time_reference": {
                    "label": "demain soir",
                    "resolved_date": "2026-03-30",
                    "relative_reference": "tomorrow",
                    "window": "evening",
                },
            },
            source_text="Je ne suis pas dispo demain soir",
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
        trigger_activity: str | None = None,
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
            trigger_activity=trigger_activity,
        )

    def test_builder_produces_fact_with_expires_at_anchored_on_window_end(self) -> None:
        indication = self._make(
            source_text="Je n'ai pas acces a la piscine pendant 2 semaines",
            start=date(2026, 4, 20),
            end=date(2026, 5, 3),
            trigger_activity="swimming",
        )
        payloads = build_availability_fact_payloads_from_indication(indication)
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["category"], "availability")
        self.assertEqual(payload["key"], "unavailable_swimming_2026-04-20_2026-05-03")
        self.assertIn("piscine", payload["value"].lower())
        # expires_at ancré à J+1 minuit (le fact reste actif tout le dernier jour)
        self.assertEqual(payload["expires_at"], datetime(2026, 5, 4, 0, 0))

    def test_builder_does_not_infer_activity_from_source_text(self) -> None:
        indication = self._make(
            source_text="Je n'ai pas acces a la piscine pendant 2 semaines",
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
