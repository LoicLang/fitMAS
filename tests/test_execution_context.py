from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.execution_context import build_today_execution_context


class ExecutionContextTest(unittest.TestCase):
    def test_marks_off_plan_done_when_today_activity_is_different_sport(self) -> None:
        context = build_today_execution_context(
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T00:00:00+01:00",
                    "sport_type": "swimming",
                    "session_title": "Natation technique",
                    "duration_min": 60,
                    "completion_status": "planned",
                }
            ],
            activities=[
                {
                    "id": 71,
                    "started_at": "2026-03-22T18:10:00+01:00",
                    "sport_type": "running",
                    "title": "Course reprise",
                    "duration_min": 30,
                    "scheduled_session_id": None,
                }
            ],
        )

        self.assertEqual(context.execution_status, "off_plan_done")
        self.assertEqual(context.actual_sports_today, ("running",))
        self.assertEqual(context.actual_duration_min_today, 30)
        self.assertEqual(context.planned_sport, "swimming")

    def test_marks_same_sport_activity_without_link_as_candidate(self) -> None:
        context = build_today_execution_context(
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T00:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing 60 min",
                    "duration_min": 60,
                    "completion_status": "planned",
                }
            ],
            activities=[
                {
                    "id": 71,
                    "started_at": "2026-03-22T18:10:00+01:00",
                    "sport_type": "running",
                    "title": "Course reprise",
                    "duration_min": 30,
                    "scheduled_session_id": None,
                }
            ],
        )

        self.assertEqual(context.execution_status, "planned_done_candidate")
        self.assertIn("sans lien explicite", context.status_reason.lower())

    def test_marks_planned_done_as_expected_when_linked_activity_exists(self) -> None:
        context = build_today_execution_context(
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T00:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing 45 min",
                    "duration_min": 45,
                    "completion_status": "done",
                }
            ],
            activities=[
                {
                    "id": 71,
                    "started_at": "2026-03-22T18:10:00+01:00",
                    "sport_type": "running",
                    "title": "Course reprise",
                    "duration_min": 46,
                    "scheduled_session_id": 12,
                }
            ],
        )

        self.assertEqual(context.execution_status, "planned_done_as_expected")
        self.assertEqual(context.linked_activity_id, 71)

    def test_marks_planned_pending_when_no_activity_today(self) -> None:
        context = build_today_execution_context(
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T00:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing 45 min",
                    "duration_min": 45,
                    "completion_status": "planned",
                }
            ],
            activities=[],
        )

        self.assertEqual(context.execution_status, "planned_pending")
        self.assertEqual(context.activity_count_today, 0)

    def test_marks_off_plan_done_without_today_plan(self) -> None:
        context = build_today_execution_context(
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:55:00+01:00"),
            scheduled_sessions=[],
            activities=[
                {
                    "id": 71,
                    "started_at": "2026-03-22T18:10:00+01:00",
                    "sport_type": "cycling",
                    "title": "Sortie velo",
                    "duration_min": 50,
                    "scheduled_session_id": None,
                }
            ],
        )

        self.assertEqual(context.execution_status, "off_plan_done")
        self.assertEqual(context.actual_sports_today, ("cycling",))


if __name__ == "__main__":
    unittest.main()
