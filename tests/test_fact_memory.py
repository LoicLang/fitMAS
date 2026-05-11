from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fitmas.fact_memory import (
    derive_fact_memory_policy,
    fact_is_current,
    normalize_fact_payload,
    select_readiness_facts,
    select_relevant_facts,
)


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

    def test_normalize_health_fact_adds_lifecycle_and_readiness_affect(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        payload = normalize_fact_payload(
            {
                "category": "health",
                "key": "health_tibia",
                "value": "Tension tibia gauche a surveiller",
                "source": "conversation",
            },
            now=now,
        )

        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["observed_at"], now)
        self.assertEqual(payload["valid_from"], now)
        self.assertEqual(payload["valid_until"], payload["expires_at"])
        self.assertEqual(payload["last_seen_at"], now)
        self.assertIn("readiness", payload["affects"])

    def test_normalize_mild_health_signal_uses_short_validity_from_structured_severity(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        payload = normalize_fact_payload(
            {
                "category": "health",
                "key": "health_tibia",
                "value": "Signal sante structure",
                "source": "conversation",
                "signal_kind": "tension",
                "severity": "mild",
            },
            now=now,
        )

        self.assertEqual(payload["ttl"], "short")
        self.assertEqual(payload["valid_until"], now.replace(tzinfo=None) + timedelta(days=3))

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

    def test_fact_is_current_rejects_resolved_and_temporally_invalid_facts(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        self.assertFalse(
            fact_is_current(
                {
                    "active": True,
                    "status": "resolved",
                    "valid_until": now + timedelta(days=3),
                },
                now=now,
            )
        )
        self.assertFalse(
            fact_is_current(
                {
                    "active": True,
                    "status": "open",
                    "valid_until": now - timedelta(minutes=1),
                },
                now=now,
            )
        )
        self.assertFalse(
            fact_is_current(
                {
                    "active": True,
                    "status": "open",
                    "valid_from": now + timedelta(days=1),
                },
                now=now,
            )
        )

    def test_select_readiness_facts_keeps_only_open_temporal_readiness_facts(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

        selected = select_readiness_facts(
            [
                {
                    "category": "health",
                    "key": "old_tendon",
                    "value": "Ancienne tension tendon reglee",
                    "active": True,
                    "status": "resolved",
                    "affects": ["readiness"],
                    "valid_until": now + timedelta(days=3),
                },
                {
                    "category": "coaching",
                    "key": "sleep_preference",
                    "value": "Douche froide interessante pour le sommeil",
                    "active": True,
                    "status": "open",
                    "affects": ["conversation"],
                },
                {
                    "category": "health",
                    "key": "tibia_watch",
                    "value": "Tension tibia legere, pas de douleur",
                    "active": True,
                    "status": "open",
                    "affects": ["readiness"],
                    "valid_from": now - timedelta(hours=1),
                    "valid_until": now + timedelta(days=2),
                    "urgency": "medium",
                },
            ],
            now=now,
        )

        self.assertEqual([fact["key"] for fact in selected], ["tibia_watch"])


if __name__ == "__main__":
    unittest.main()
