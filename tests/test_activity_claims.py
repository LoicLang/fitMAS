from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.activity_claims import (
    build_claim_fact_payloads,
    extract_activity_claim,
    extract_recent_activity_claim,
)


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

    def test_builds_execution_fact_for_unlogged_claim(self) -> None:
        claim = extract_recent_activity_claim(
            [{"role": "user", "text": "J'ai couru aujourd'hui"}],
            current_text="J'ai fait 30 min",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        payloads = build_claim_fact_payloads(
            claim,
            activities=[],
            timezone_name="Europe/Paris",
        )

        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["category"], "execution")
        self.assertIn("running", payloads[0]["key"])
        self.assertIn("30 min", payloads[0]["value"])

    def test_skips_execution_fact_when_activity_already_logged(self) -> None:
        claim = extract_activity_claim(
            "J'ai couru aujourd'hui 30 min",
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        payloads = build_claim_fact_payloads(
            claim,
            activities=[
                {
                    "sport_type": "running",
                    "duration_min": 28,
                    "started_at": datetime.fromisoformat("2026-03-22T18:00:00+01:00"),
                }
            ],
            timezone_name="Europe/Paris",
        )

        self.assertEqual(payloads, [])


if __name__ == "__main__":
    unittest.main()
