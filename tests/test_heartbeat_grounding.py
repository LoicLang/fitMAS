from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-heartbeat-", suffix=".db"))

import fitmas.heartbeat as heartbeat
from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class HeartbeatGroundingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris", coach_name="FitMAS", coach_style="direct")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()
        heartbeat._LAST_PROACTIVE_GUARD_AT.clear()

    def test_weekly_review_prompt_mentions_actual_activities(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="cycling",
            title="Sortie velo",
            duration_min=35,
            distance_m=10000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=now - timedelta(days=1),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=20.0,
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Activites reelles detectees sur 7 jours: 1", captured["prompt"])
        self.assertIn("Duree reelle totale: 35 min", captured["prompt"])

    def test_morning_briefing_mentions_yesterday_off_plan_activity(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "technique",
                    "session_title": "Natation",
                    "session_goal": "Precision",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 60,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Seance cle",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="running",
            title="Course off-plan",
            duration_min=30,
            distance_m=5000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=now - timedelta(days=1),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=24.0,
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("activite reelle detectee", captured["prompt"].lower())
        self.assertIn("30 min", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
