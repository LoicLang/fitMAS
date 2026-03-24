from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fitmas.fact_memory import derive_fact_memory_policy, fact_is_current, normalize_fact_payload, select_relevant_facts


class FactMemoryTest(unittest.TestCase):
    def test_derive_immediate_ttl_for_fatigue(self) -> None:
        policy = derive_fact_memory_policy(
            category="fatigue",
            value="Fatigue residuelle aujourd'hui",
            source="conversation",
            now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(policy.ttl, "immediate")
        self.assertEqual(policy.urgency, "high")
        self.assertIsNotNone(policy.expires_at)

    def test_derive_permanent_ttl_for_onboarding_preference(self) -> None:
        policy = derive_fact_memory_policy(
            category="preference",
            value="Plutot le matin",
            source="onboarding",
            now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(policy.ttl, "permanent")
        self.assertIsNone(policy.expires_at)

    def test_normalize_fact_payload_fills_memory_fields(self) -> None:
        payload = normalize_fact_payload(
            {
                "category": "constraint",
                "key": "thursday_busy",
                "value": "Jeudi soir je suis pris",
                "source": "conversation",
                "confidence": 0.8,
                "confirmed": True,
            },
            now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["ttl"], "medium")
        self.assertEqual(payload["urgency"], "medium")
        self.assertIn("planning", payload["affects"])
        self.assertIsNotNone(payload["expires_at"])

    def test_select_relevant_facts_prefers_current_confirmed(self) -> None:
        selected = select_relevant_facts(
            [
                {
                    "category": "preference",
                    "key": "morning",
                    "value": "Plutot le matin",
                    "confidence": 0.7,
                    "confirmed": True,
                    "active": True,
                    "urgency": "low",
                    "affects": ["planning"],
                },
                {
                    "category": "fatigue",
                    "key": "legs",
                    "value": "Jambes lourdes aujourd'hui",
                    "confidence": 0.9,
                    "confirmed": True,
                    "active": True,
                    "urgency": "high",
                    "affects": ["conversation", "heartbeat"],
                },
            ],
            affects=["conversation"],
        )

        self.assertEqual(selected[0], "[fatigue] Jambes lourdes aujourd'hui")

    def test_fact_is_current_respects_expiration(self) -> None:
        self.assertFalse(
            fact_is_current(
                {
                    "active": True,
                    "expires_at": "2026-03-20T10:00:00+00:00",
                },
                now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            )
        )


if __name__ == "__main__":
    unittest.main()
