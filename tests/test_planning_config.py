from __future__ import annotations

import unittest

from fitmas.legacy.domain.planning.planning_config import (
    SUPPORTED_SPORTS,
    get_global_planning_config,
    get_level_planning_config,
    get_sport_planning_config,
)


class PlanningConfigTest(unittest.TestCase):
    def test_global_defaults_are_exposed(self) -> None:
        config = get_global_planning_config()
        self.assertGreaterEqual(config.max_key_sessions_per_week, 1)
        self.assertGreaterEqual(config.max_llm_validation_retries, 1)
        self.assertLess(config.tsb_floor, 0)

    def test_sport_configs_cover_supported_sports(self) -> None:
        for sport in SUPPORTED_SPORTS:
            config = get_sport_planning_config(sport)
            self.assertEqual(config.sport, sport)
            self.assertGreater(config.max_session_duration_min, config.min_session_duration_min)

    def test_unknown_keys_fallback_safely(self) -> None:
        sport_config = get_sport_planning_config("ski")
        level_config = get_level_planning_config("elite")
        self.assertEqual(sport_config.sport, "running")
        self.assertEqual(level_config.level, "unknown")


if __name__ == "__main__":
    unittest.main()
