from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fitmas.memory_routing import split_memory_payloads


class MemoryRoutingTest(unittest.TestCase):
    def test_split_memory_payloads_routes_short_lived_items_to_working_memory(self) -> None:
        profile_payloads, working_payloads = split_memory_payloads(
            [
                {
                    "category": "fatigue",
                    "key": "legs_today",
                    "value": "Jambes lourdes aujourd'hui",
                    "source": "conversation",
                },
                {
                    "category": "preference",
                    "key": "morning",
                    "value": "Plutot le matin",
                    "source": "conversation",
                },
            ],
            now=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(profile_payloads), 1)
        self.assertEqual(len(working_payloads), 1)
        self.assertEqual(profile_payloads[0]["category"], "preference")
        self.assertEqual(working_payloads[0]["category"], "fatigue")
        self.assertEqual(working_payloads[0]["scope"], "day")


if __name__ == "__main__":
    unittest.main()
