from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-tests-", suffix=".db"))

from fastapi.testclient import TestClient

import fitmas.api_messages as api_messages
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import MutationDecision
from fitmas.plan_actions import move_session
from fitmas.training_load import compute_ctl_atl_tsb, estimate_tss
from fitmas import repository as repo, schema as s
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class FitMASCoreFlowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            age=31,
            primary_objective="reprendre",
            objective="reprendre",
            coach_name="FitMAS",
            coach_style="direct",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def _create_plan_for_today(self) -> tuple[s.WeeklyPlan, s.ScheduledSession]:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        plan = repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing facile",
                    "session_goal": "Reprendre",
                    "session_note": "souple",
                    "session_description": "40 min",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 2,
                    "priority": "Normal",
                    "nutrition_focus": "Hydratation",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(session)
        return plan, session

    def test_move_session_keeps_placeholder_and_creates_future_copy(self) -> None:
        _, session = self._create_plan_for_today()
        moved = move_session(
            self.db,
            user=self.user,
            session_id=session.id,
            target_date=session.scheduled_date.date() + timedelta(days=8),
        )
        self.assertIsNotNone(moved)
        sessions = [repo.to_pydantic_scheduled_session(x) for x in repo.get_scheduled_sessions(self.db, self.user.id, limit=10)]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].sport_type, "rest")
        self.assertEqual(sessions[0].completion_status, "adapted")
        self.assertEqual(sessions[1].session_title, "Footing facile")
        self.assertEqual(sessions[1].scheduled_date, (session.scheduled_date.date() + timedelta(days=8)).isoformat())

    def test_message_flow_can_lighten_targeted_session(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="lighten_day",
                target_session_id=session.id,
                rationale="On leve le pied aujourd'hui.",
                fitmas_message="On allège aujourd'hui. Tu récupères.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "je suis cramé"}).json()
            today = self.client.get("/api/v0/today").json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(result["assistant_message"]["text"], "On allège aujourd'hui. Tu récupères.")
        self.assertEqual(today["completion_status"], "adapted")
        self.assertEqual(today["sport_type"], "rest")

    def test_training_load_outputs_are_stable(self) -> None:
        activities = [
            {"started_at": "2026-03-15T08:00:00+00:00", "tss": 42.0},
            {"started_at": "2026-03-18T08:00:00+00:00", "tss": 55.0},
            {"started_at": "2026-03-21T08:00:00+00:00", "tss": 38.0},
        ]
        estimated = estimate_tss(
            {"sport_type": "running", "duration_min": 60, "avg_hr": 150},
            self.user,
        )
        load = compute_ctl_atl_tsb(activities, as_of_date="2026-03-22")
        self.assertIsNotNone(estimated)
        self.assertGreater(estimated, 0)
        self.assertEqual(load["as_of_date"], "2026-03-22")
        self.assertIn("series", load)
        self.assertGreater(len(load["series"]), 0)


if __name__ == "__main__":
    unittest.main()
