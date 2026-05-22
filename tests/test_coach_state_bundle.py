from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-bundle-tests-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.domain.coaching.coach_state import build_coach_state_bundle
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.core.time_context import DAY_KEYS, day_label_fr, get_local_now


class CoachStateBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            age=31,
            objective="reprendre",
            primary_objective="reprendre",
            coach_name="FitMAS",
            coach_style="direct",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_build_coach_state_bundle_returns_shared_runtime_truth(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=self.user.timezone,
            mesocycle_week=2,
            mesocycle_number=1,
            total_weeks=6,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "tempo",
                    "session_title": "Tempo run",
                    "session_goal": "Tenir l'allure",
                    "session_note": "Reste propre",
                    "session_description": "20' tempo",
                    "duration_min": 55,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Cle",
                    "nutrition_focus": "Hydratation",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        scheduled_sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=42)
        activities = repo.get_activities(self.db, self.user.id, limit=120)
        planning_decision = repo.get_latest_planning_decision_record(self.db, self.user.id)
        week_plan = repo.to_pydantic_plan(repo.get_active_plan(self.db, self.user.id))

        bundle = build_coach_state_bundle(
            self.db,
            user=self.user,
            today_date=now.date(),
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            planning_decision=planning_decision,
            week_plan=week_plan,
            recent_adaptations_limit=4,
            screen="overview",
        )

        self.assertEqual(bundle.today_date, now.date())
        self.assertTrue(bundle.session_policies)
        self.assertEqual(bundle.week_summary["total_sessions"], 1)
        self.assertIn("mode", bundle.planning_context)
        self.assertIn("target_tss", bundle.planning_context)
        self.assertIn("focus", bundle.next_week)
        self.assertTrue(bundle.coach_reading.strip())


if __name__ == "__main__":
    unittest.main()
