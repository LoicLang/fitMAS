from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from fitmas.legacy.domain.execution import repository as execution_repo
from fitmas.legacy.domain.memory import repository as memory_repo
from fitmas.legacy.domain.planning import template_repository as template_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-signals-", suffix=".db"))

from fitmas.legacy.core import orm as s
from fitmas.legacy.core.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.domain.coaching.signals import collect_signals, format_signals_for_prompt
from fitmas.legacy.core.time_context import DAY_KEYS, day_label_fr, get_local_now


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

    def test_collect_signals_returns_empty_without_active_plan(self) -> None:
        self.assertEqual(collect_signals(self.db, self.user), [])

    def test_format_signals_for_prompt_hides_internal_tags(self) -> None:
        block = format_signals_for_prompt(
            [
                {
                    "kind": "high_cumulative_load",
                    "severity": "warning",
                    "summary": "Charge elevee cette semaine.",
                    "data": {},
                }
            ]
        )

        self.assertIn("Signaux utiles:", block)
        self.assertIn("- Charge elevee cette semaine.", block)
        self.assertNotIn("high_cumulative_load", block)
        self.assertNotIn("warning", block)
        self.assertNotIn("\u26a0\ufe0f", block)

    def test_missed_key_session_uses_scheduled_session_without_active_plan(self) -> None:
        now = get_local_now(self.user.timezone)
        yesterday = now - timedelta(days=1)
        yesterday_key = DAY_KEYS[yesterday.weekday()]
        session = s.ScheduledSession(
            user_id=self.user.id,
            day=yesterday_key,
            label=day_label_fr(yesterday_key, capitalize=True),
            scheduled_date=yesterday.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None),
            sport_type="swimming",
            session_type="technique",
            session_title="Natation cle",
            session_goal="Precision",
            session_note="",
            session_description="",
            duration_min=60,
            intensity="moderate",
            load_score=3,
            priority="Seance cle",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        execution_repo.add_activity(
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

        signals = collect_signals(self.db, self.user)
        missed = next(signal for signal in signals if signal["kind"] == "missed_key_session")

        self.assertEqual(missed["data"]["session_id"], session.id)
        self.assertIn("running", missed["data"]["actual_sports"])
        self.assertIn("hors seance prevue", missed["summary"])

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
        template_repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=days,
        )
        execution_repo.add_activity(
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
        yesterday = now - timedelta(days=1)
        yesterday_key = DAY_KEYS[yesterday.weekday()]
        self.db.add(
            s.ScheduledSession(
                user_id=self.user.id,
                day=yesterday_key,
                label=day_label_fr(yesterday_key, capitalize=True),
                scheduled_date=yesterday.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None),
                sport_type="swimming",
                session_type="technique",
                session_title="Natation cle",
                session_goal="Precision",
                session_note="",
                session_description="",
                duration_min=60,
                intensity="moderate",
                load_score=3,
                priority="Seance cle",
                nutrition_focus="",
                flexibility="stable",
                completion_status="planned",
            )
        )
        self.db.commit()
        execution_repo.add_activity(
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
        template_repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=days,
        )
        memory_repo.upsert_facts(
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
