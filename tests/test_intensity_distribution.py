from __future__ import annotations

import unittest

from fitmas.intensity_distribution import (
    check_distribution,
    classify_session_intensity,
    compute_intensity_budget,
)


class TestIntensityBudget(unittest.TestCase):
    def test_maintain_load_80_20(self) -> None:
        budget = compute_intensity_budget("maintain_load", 300)
        self.assertAlmostEqual(budget.low_pct, 0.80)
        self.assertAlmostEqual(budget.moderate_pct, 0.05)
        self.assertAlmostEqual(budget.high_pct, 0.15)
        self.assertEqual(budget.low_minutes, 240)
        self.assertEqual(budget.high_minutes, 45)

    def test_deload_no_high(self) -> None:
        budget = compute_intensity_budget("deload", 200)
        self.assertAlmostEqual(budget.high_pct, 0.00)
        self.assertEqual(budget.high_minutes, 0)

    def test_injury_protection_all_low(self) -> None:
        budget = compute_intensity_budget("injury_protection", 150)
        self.assertAlmostEqual(budget.low_pct, 1.00)
        self.assertEqual(budget.low_minutes, 150)


class TestClassification(unittest.TestCase):
    def test_z1_z2_low(self) -> None:
        self.assertEqual(classify_session_intensity("Z1"), "low")
        self.assertEqual(classify_session_intensity("Z2"), "low")

    def test_z3_moderate(self) -> None:
        self.assertEqual(classify_session_intensity("Z3"), "moderate")

    def test_z4_z5_high(self) -> None:
        self.assertEqual(classify_session_intensity("Z4"), "high")
        self.assertEqual(classify_session_intensity("Z5"), "high")


class TestCheckDistribution(unittest.TestCase):
    def test_balanced_week_no_warnings(self) -> None:
        sessions = [
            {"sport_type": "running", "duration_min": 45, "intensity": "easy", "target_zone": "Z1"},
            {"sport_type": "running", "duration_min": 45, "intensity": "easy", "target_zone": "Z1"},
            {"sport_type": "running", "duration_min": 55, "intensity": "hard", "target_zone": "Z5"},
            {"sport_type": "running", "duration_min": 75, "intensity": "moderate", "target_zone": "Z2"},
            {"sport_type": "rest", "duration_min": 0},
        ]
        # 55 high / 220 total = 25% — right at threshold
        warnings = check_distribution(sessions, "maintain_load")
        self.assertEqual(len(warnings), 0)

    def test_too_much_tempo_warns(self) -> None:
        sessions = [
            {"sport_type": "running", "duration_min": 50, "intensity": "moderate", "target_zone": "Z3"},
            {"sport_type": "running", "duration_min": 50, "intensity": "moderate", "target_zone": "Z3"},
            {"sport_type": "running", "duration_min": 40, "intensity": "easy", "target_zone": "Z1"},
        ]
        warnings = check_distribution(sessions, "maintain_load")
        self.assertTrue(any("Z3 moderate" in w for w in warnings))

    def test_deload_with_high_warns(self) -> None:
        sessions = [
            {"sport_type": "running", "duration_min": 45, "intensity": "easy", "target_zone": "Z1"},
            {"sport_type": "running", "duration_min": 55, "intensity": "hard", "target_zone": "Z5"},
        ]
        warnings = check_distribution(sessions, "deload")
        self.assertTrue(any("Deload" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
