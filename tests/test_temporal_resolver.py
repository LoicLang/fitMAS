from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.core.temporal_resolver import resolve_temporal_context


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

    def test_explicit_day_resolves_to_next_occurrence(self) -> None:
        resolution = resolve_temporal_context(
            "je voyage mercredi",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-29T08:00:00+02:00"),
        )

        self.assertEqual(resolution.primary_reference, "explicit_wednesday")
        self.assertEqual(resolution.resolved_date.isoformat(), "2026-04-01")

    def test_keeps_explicit_day_when_relative_reference_is_present(self) -> None:
        resolution = resolve_temporal_context(
            "non laisse la piscine demain, on est jeudi demain",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-04-08T08:14:00+02:00"),
        )

        self.assertEqual(resolution.primary_reference, "tomorrow")
        self.assertEqual(resolution.resolved_date.isoformat(), "2026-04-09")
        self.assertEqual(resolution.explicit_day_key, "thursday")
        self.assertTrue(resolution.explicit_day_matches_resolved_date)
        self.assertIn("explicit_thursday", resolution.references)


if __name__ == "__main__":
    unittest.main()
