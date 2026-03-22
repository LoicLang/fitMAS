from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-signals-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.signals import collect_signals
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class SignalsGroundingTest(unittest.TestCase):
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

    def test_silence_signal_ignores_recent_off_plan_activity(self) -> None:
        now = get_local_now(self.user.timezone)
        days = []
        for offset in range(3):
            day_key = DAY_KEYS[(now.weekday() - offset) % 7]
            days.append(
                {
                    "day": day_key,
                    "label": day_label_fr(day_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            )
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=days,
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

        kinds = {signal["kind"] for signal in collect_signals(self.db, self.user)}

        self.assertNotIn("silence_3_days", kinds)

    def test_missed_key_session_mentions_actual_activity(self) -> None:
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
                    "session_title": "Natation cle",
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
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Repos",
                    "session_goal": "Repos",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": None,
                    "intensity": "easy",
                    "load_score": 0,
                    "priority": "Souplesse",
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

        missed = next(signal for signal in collect_signals(self.db, self.user) if signal["kind"] == "missed_key_session")

        self.assertIn("running", missed["data"]["actual_sports"])
        self.assertIn("hors seance prevue", missed["summary"])

    def test_silence_signal_ignores_claimed_activity(self) -> None:
        now = get_local_now(self.user.timezone)
        days = []
        for offset in range(3):
            day_key = DAY_KEYS[(now.weekday() - offset) % 7]
            days.append(
                {
                    "day": day_key,
                    "label": day_label_fr(day_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            )
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=days,
        )
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "execution",
                    "key": f"claimed_activity_{(now.date() - timedelta(days=1)).isoformat()}_running",
                    "value": f"Activite declaree par l'utilisateur: running, 30 min, date {(now.date() - timedelta(days=1)).isoformat()}, non loggee.",
                    "confidence": 0.9,
                    "confirmed": True,
                    "source": "conversation",
                }
            ],
        )

        kinds = {signal["kind"] for signal in collect_signals(self.db, self.user)}

        self.assertNotIn("silence_3_days", kinds)


if __name__ == "__main__":
    unittest.main()
