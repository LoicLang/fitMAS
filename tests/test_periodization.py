from __future__ import annotations

import unittest

from fitmas.periodization import (
    adjust_planning_mode,
    compute_mesocycle_state,
    get_reps_multiplier,
    get_tss_multiplier,
    get_volume_multiplier,
    should_force_deload,
)


class TestMesocycleState(unittest.TestCase):
    def test_week_1_baseline(self) -> None:
        state = compute_mesocycle_state(total_weeks=1)
        self.assertEqual(state.cycle_number, 1)
        self.assertEqual(state.week_in_cycle, 1)
        self.assertFalse(state.is_recovery_week)
        self.assertEqual(state.progression_level, 1.0)

    def test_week_3_peak(self) -> None:
        state = compute_mesocycle_state(total_weeks=3)
        self.assertEqual(state.cycle_number, 1)
        self.assertEqual(state.week_in_cycle, 3)
        self.assertFalse(state.is_recovery_week)

    def test_week_4_recovery(self) -> None:
        state = compute_mesocycle_state(total_weeks=4)
        self.assertEqual(state.cycle_number, 1)
        self.assertEqual(state.week_in_cycle, 4)
        self.assertTrue(state.is_recovery_week)

    def test_week_5_new_cycle(self) -> None:
        state = compute_mesocycle_state(total_weeks=5)
        self.assertEqual(state.cycle_number, 2)
        self.assertEqual(state.week_in_cycle, 1)
        self.assertFalse(state.is_recovery_week)

    def test_week_8_second_recovery(self) -> None:
        state = compute_mesocycle_state(total_weeks=8)
        self.assertEqual(state.cycle_number, 2)
        self.assertEqual(state.week_in_cycle, 4)
        self.assertTrue(state.is_recovery_week)

    def test_progression_level_increases(self) -> None:
        w1 = compute_mesocycle_state(total_weeks=1)
        w3 = compute_mesocycle_state(total_weeks=3)
        w5 = compute_mesocycle_state(total_weeks=5)
        self.assertLess(w1.progression_level, w3.progression_level)
        self.assertLess(w3.progression_level, w5.progression_level)


class TestMultipliers(unittest.TestCase):
    def test_week_1_baseline(self) -> None:
        self.assertAlmostEqual(get_tss_multiplier(1), 1.0)
        self.assertAlmostEqual(get_volume_multiplier(1), 1.0)

    def test_week_2_plus_5_pct(self) -> None:
        self.assertAlmostEqual(get_tss_multiplier(2), 1.05)

    def test_week_3_plus_8_pct(self) -> None:
        self.assertAlmostEqual(get_tss_multiplier(3), 1.08)

    def test_week_4_recovery(self) -> None:
        self.assertAlmostEqual(get_tss_multiplier(4), 0.65)
        self.assertAlmostEqual(get_volume_multiplier(4), 0.80)
        self.assertAlmostEqual(get_reps_multiplier(4), 0.50)


class TestDeloadLogic(unittest.TestCase):
    def test_force_deload_week_4(self) -> None:
        self.assertTrue(should_force_deload(4))

    def test_no_deload_week_3(self) -> None:
        self.assertFalse(should_force_deload(3))

    def test_adjust_mode_week_4(self) -> None:
        self.assertEqual(adjust_planning_mode("increase_load", 4), "deload")

    def test_adjust_mode_week_2_no_change(self) -> None:
        self.assertEqual(adjust_planning_mode("increase_load", 2), "increase_load")


if __name__ == "__main__":
    unittest.main()
