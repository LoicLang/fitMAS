from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from fitmas.legacy.domain.memory.patterns import derive_pattern_payloads


class MemoryPatternsTest(unittest.TestCase):
    def test_derive_pattern_payloads_promotes_recurring_unavailable_slot(self) -> None:
        messages = [
            SimpleNamespace(role="user", text="Merde, je peux pas ce soir", created_at=datetime(2026, 3, 3, 17, 30, tzinfo=timezone.utc)),
            SimpleNamespace(role="user", text="Je peux pas ce soir finalement", created_at=datetime(2026, 3, 10, 17, 45, tzinfo=timezone.utc)),
            SimpleNamespace(role="user", text="Imprevu, je peux pas ce soir", created_at=datetime(2026, 3, 17, 17, 15, tzinfo=timezone.utc)),
        ]

        payloads = derive_pattern_payloads(
            timezone_name="Europe/Paris",
            user_messages=messages,
            activities=[],
            adaptation_events=[],
            now=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
        )

        recurring = next(payload for payload in payloads if payload["pattern_type"] == "recurring_unavailable_slot")
        self.assertEqual(recurring["category"], "availability")
        self.assertEqual(recurring["key"], "recurring_unavailable_tuesday_evening")
        self.assertEqual(recurring["evidence_count"], 3)

    def test_derive_pattern_payloads_promotes_preferred_training_window(self) -> None:
        activities = [
            SimpleNamespace(started_at=datetime(2026, 3, 2, 6, 45, tzinfo=timezone.utc)),
            SimpleNamespace(started_at=datetime(2026, 3, 4, 7, 15, tzinfo=timezone.utc)),
            SimpleNamespace(started_at=datetime(2026, 3, 7, 8, 0, tzinfo=timezone.utc)),
            SimpleNamespace(started_at=datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc)),
            SimpleNamespace(started_at=datetime(2026, 3, 12, 7, 0, tzinfo=timezone.utc)),
            SimpleNamespace(started_at=datetime(2026, 3, 15, 17, 45, tzinfo=timezone.utc)),
        ]

        payloads = derive_pattern_payloads(
            timezone_name="Europe/Paris",
            user_messages=[],
            activities=activities,
            adaptation_events=[],
            now=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
        )

        preferred = next(payload for payload in payloads if payload["pattern_type"] == "preferred_training_window")
        self.assertEqual(preferred["category"], "preference")
        self.assertEqual(preferred["key"], "preferred_training_window_morning")
        self.assertEqual(preferred["evidence_count"], 5)


if __name__ == "__main__":
    unittest.main()
