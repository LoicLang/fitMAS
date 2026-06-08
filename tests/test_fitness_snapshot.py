from __future__ import annotations

import unittest

from fitmas.legacy.domain.athlete.fitness_snapshot import build_fitness_snapshot, estimate_scheduled_session_tss


class FitnessSnapshotTest(unittest.TestCase):
    def test_build_fitness_snapshot_aggregates_recent_training_state(self) -> None:
        activities = [
            {
                "sport_type": "running",
                "started_at": "2026-03-17T07:00:00+01:00",
                "duration_min": 60,
                "tss": 50.0,
            },
            {
                "sport_type": "swimming",
                "started_at": "2026-03-19T07:00:00+01:00",
                "duration_min": 45,
                "tss": 30.0,
            },
            {
                "sport_type": "running",
                "started_at": "2026-03-22T09:00:00+01:00",
                "duration_min": 80,
                "tss": 70.0,
            },
            {
                "sport_type": "cycling",
                "started_at": "2026-03-12T09:00:00+01:00",
                "duration_min": 60,
                "tss": 40.0,
            },
        ]
        scheduled_sessions = [
            {
                "sport_type": "running",
                "scheduled_date": "2026-03-17T07:00:00+01:00",
                "duration_min": 60,
                "intensity": "moderate",
                "priority": "High",
                "load_score": 3,
                "completion_status": "done",
            },
            {
                "sport_type": "swimming",
                "scheduled_date": "2026-03-19T07:00:00+01:00",
                "duration_min": 45,
                "intensity": "easy",
                "priority": "Normal",
                "load_score": 1,
                "completion_status": "done",
            },
            {
                "sport_type": "running",
                "scheduled_date": "2026-03-22T09:00:00+01:00",
                "duration_min": 80,
                "intensity": "hard",
                "priority": "High",
                "load_score": 4,
                "completion_status": "done",
            },
            {
                "sport_type": "strength",
                "scheduled_date": "2026-03-21T18:00:00+01:00",
                "duration_min": 30,
                "intensity": "easy",
                "priority": "Normal",
                "load_score": 1,
                "completion_status": "planned",
            },
        ]

        snapshot = build_fitness_snapshot(
            user_id=7,
            activities=activities,
            scheduled_sessions=scheduled_sessions,
            as_of_date="2026-03-22",
        )

        self.assertEqual(snapshot.user_id, 7)
        self.assertEqual(snapshot.date.isoformat(), "2026-03-22")
        self.assertEqual(snapshot.weekly_actual_tss, 150.0)
        self.assertGreater(snapshot.weekly_target_tss, snapshot.weekly_actual_tss)
        self.assertEqual(snapshot.completion_rate_14d, 0.75)
        self.assertEqual(snapshot.key_sessions_done_14d, 2)
        self.assertEqual(snapshot.volume_sessions_done_14d, 1)
        self.assertGreater(snapshot.ctl, 0.0)
        self.assertLess(snapshot.tsb, 0.0)
        self.assertEqual(snapshot.sport_volume_hours["running"], 2.3)
        self.assertEqual(snapshot.sport_volume_hours["cycling"], 1.0)
        self.assertIn("swimming", snapshot.sport_ctl)

    def test_build_fitness_snapshot_handles_empty_history(self) -> None:
        snapshot = build_fitness_snapshot(user_id=9, activities=[], scheduled_sessions=[], as_of_date="2026-03-22")

        self.assertEqual(snapshot.weekly_actual_tss, 0.0)
        self.assertEqual(snapshot.weekly_target_tss, 0.0)
        self.assertEqual(snapshot.completion_rate_14d, 0.0)
        self.assertEqual(snapshot.key_sessions_done_14d, 0)
        self.assertEqual(snapshot.volume_sessions_done_14d, 0)
        self.assertTrue(all(value == 0.0 for value in snapshot.sport_ctl.values()))
        self.assertTrue(all(value == 0.0 for value in snapshot.sport_volume_hours.values()))

    def test_estimate_scheduled_session_tss_respects_sport_and_intensity(self) -> None:
        running_easy = estimate_scheduled_session_tss(
            {"sport_type": "running", "duration_min": 60, "intensity": "easy"}
        )
        swimming_hard = estimate_scheduled_session_tss(
            {"sport_type": "swimming", "duration_min": 60, "intensity": "hard"}
        )
        rest = estimate_scheduled_session_tss(
            {"sport_type": "rest", "duration_min": 60, "intensity": "easy"}
        )

        self.assertGreater(swimming_hard, 40.0)
        self.assertLess(running_easy, 55.0)
        self.assertEqual(rest, 0.0)


if __name__ == "__main__":
    unittest.main()
