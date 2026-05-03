from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-matching-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.activities import match_activity_to_day
from fitmas.db import Base, SessionLocal, engine, init_db


class ActivityMatchingTruthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_match_activity_to_day_refuses_different_sport_same_day(self) -> None:
        matched_day, reason = match_activity_to_day(
            sport_type="running",
            started_at=datetime.fromisoformat("2026-03-30T07:30:00"),
            duration_min=35,
            scheduled_sessions=[
                SimpleNamespace(
                    day="monday",
                    scheduled_date=datetime.fromisoformat("2026-03-30T00:00:00"),
                    sport_type="swimming",
                    session_type="technique",
                    session_title="Natation",
                    session_goal="Precision",
                    session_note="",
                    session_description="",
                    duration_min=35,
                    intensity="easy",
                    load_score=1,
                    priority="Normal",
                    nutrition_focus="",
                    flexibility="flexible",
                )
            ],
        )

        self.assertIsNone(matched_day)
        self.assertEqual(reason, "")

    def test_match_activity_to_day_uses_plan_week_not_wall_clock(self) -> None:
        matched_day, reason = match_activity_to_day(
            sport_type="running",
            started_at=datetime.fromisoformat("2026-03-30T07:30:00"),
            duration_min=35,
            scheduled_sessions=[
                SimpleNamespace(
                    day="monday",
                    scheduled_date=datetime.fromisoformat("2026-03-30T00:00:00"),
                    sport_type="running",
                    session_type="easy",
                    session_title="Footing",
                    session_goal="Reprise",
                    session_note="",
                    session_description="",
                    duration_min=35,
                    intensity="easy",
                    load_score=1,
                    priority="Normal",
                    nutrition_focus="",
                    flexibility="flexible",
                )
            ],
        )

        self.assertEqual(matched_day, "monday")
        self.assertIn("meme sport", reason)

    def test_match_activity_to_day_ignores_sessions_from_other_dates(self) -> None:
        matched_day, reason = match_activity_to_day(
            sport_type="running",
            started_at=datetime.fromisoformat("2026-03-30T07:30:00"),
            duration_min=35,
            scheduled_sessions=[
                SimpleNamespace(
                    day="tuesday",
                    scheduled_date=datetime.fromisoformat("2026-03-31T00:00:00"),
                    sport_type="running",
                    session_type="easy",
                    duration_min=35,
                    flexibility="stable",
                )
            ],
        )

        self.assertIsNone(matched_day)
        self.assertEqual(reason, "")

    def test_find_scheduled_session_for_activity_returns_none_for_other_sport(self) -> None:
        session = s.ScheduledSession(
            user_id=self.user.id,
            day="monday",
            label="Lundi",
            scheduled_date=datetime.fromisoformat("2026-03-30T00:00:00"),
            sport_type="swimming",
            session_type="technique",
            session_title="Natation",
            session_goal="Precision",
            session_note="",
            session_description="",
            duration_min=45,
            intensity="easy",
            load_score=1,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()

        found = repo.find_scheduled_session_for_activity(
            self.db,
            user_id=self.user.id,
            sport_type="running",
            started_at=datetime.fromisoformat("2026-03-30T07:30:00+02:00"),
            timezone_name="Europe/Paris",
        )

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
