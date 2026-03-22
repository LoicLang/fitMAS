from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.activity_claims import extract_activity_claim, extract_recent_activity_claim


class ActivityClaimsTest(unittest.TestCase):
    def test_extracts_running_today_claim(self) -> None:
        claim = extract_activity_claim(
            "J'ai couru aujourd'hui",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.sport_type, "running")
        self.assertEqual(claim.resolved_date_iso, "2026-03-22")

    def test_extracts_duration_only_claim(self) -> None:
        claim = extract_activity_claim(
            "J'ai fait 30 min mais c'est la reprise",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.duration_min, 30)

    def test_merges_recent_claims(self) -> None:
        claim = extract_recent_activity_claim(
            [
                {"role": "user", "text": "J'ai couru aujourd'hui"},
                {"role": "agent", "text": "ok"},
            ],
            current_text="J'ai fait 30 min mais c'est la reprise",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.sport_type, "running")
        self.assertEqual(claim.duration_min, 30)
        self.assertEqual(claim.resolved_date_iso, "2026-03-22")


if __name__ == "__main__":
    unittest.main()
