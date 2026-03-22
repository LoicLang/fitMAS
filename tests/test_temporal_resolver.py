from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.temporal_resolver import resolve_temporal_context


class TemporalResolverTest(unittest.TestCase):
    def test_resolves_today(self) -> None:
        resolution = resolve_temporal_context(
            "j'ai couru aujourd'hui",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
        )

        self.assertEqual(resolution.primary_reference, "today")
        self.assertEqual(resolution.resolved_date.isoformat(), "2026-03-22")

    def test_resolves_tomorrow_morning(self) -> None:
        resolution = resolve_temporal_context(
            "demain matin je nage",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T23:30:00+01:00"),
        )

        self.assertEqual(resolution.primary_reference, "tomorrow_morning")
        self.assertEqual(resolution.part_of_day, "morning")
        self.assertEqual(resolution.resolved_date.isoformat(), "2026-03-23")

    def test_resolves_yesterday(self) -> None:
        resolution = resolve_temporal_context(
            "non c'etait hier",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
        )

        self.assertEqual(resolution.primary_reference, "yesterday")
        self.assertEqual(resolution.resolved_date.isoformat(), "2026-03-21")


if __name__ == "__main__":
    unittest.main()
