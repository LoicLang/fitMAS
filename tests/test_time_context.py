from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from fitmas.core.time_context import get_local_now, utc_now


class TimeContextOverrideTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("FITMAS_OVERRIDE_NOW_ISO", None)

    def test_get_local_now_uses_env_override_when_now_not_passed(self) -> None:
        os.environ["FITMAS_OVERRIDE_NOW_ISO"] = "2026-04-19T20:00:00+02:00"

        current = get_local_now("Europe/Paris")

        self.assertEqual(current.isoformat(), "2026-04-19T20:00:00+02:00")

    def test_explicit_now_still_wins_over_env_override(self) -> None:
        os.environ["FITMAS_OVERRIDE_NOW_ISO"] = "2026-04-19T20:00:00+02:00"

        current = get_local_now(
            "Europe/Paris",
            now=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(current.isoformat(), "2026-04-20T10:00:00+02:00")

    def test_utc_now_uses_env_override(self) -> None:
        os.environ["FITMAS_OVERRIDE_NOW_ISO"] = "2026-04-19T20:00:00+02:00"

        current = utc_now()

        self.assertEqual(current.isoformat(), "2026-04-19T18:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
