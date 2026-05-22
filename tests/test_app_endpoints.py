from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-app-tests-", suffix=".db"))

from fastapi.testclient import TestClient

from fitmas import repository as repo, schema as s
from fitmas.domain.coaching.adaptation_log import AdaptationLogEntry
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class AppEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.client = TestClient(app)
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
        self.client.close()
        self.db.close()

    def _seed_plan(self) -> s.ScheduledSession:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        plan = repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=self.user.timezone,
            mesocycle_week=2,
            mesocycle_number=3,
            total_weeks=8,
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
                },
            ],
        )
        self.assertIsNotNone(plan)
        session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(session)
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            scheduled_session_id=session.id,
            sport_type="running",
            title="Tempo du jour",
            duration_min=52,
            distance_m=10200,
            elevation_m=84,
            perceived_load=4,
            note="solide",
            started_at=session.scheduled_date.replace(hour=7, minute=30),
            matched_day=session.day,
            match_reason="manual",
            avg_hr=158,
            avg_speed=3.27,
            tss=48.0,
        )
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            scheduled_session_id=session.id,
            sport_type="cycling",
            title="Sortie vélo off-plan",
            duration_min=70,
            distance_m=28000,
            elevation_m=220,
            perceived_load=3,
            note="bonus",
            started_at=session.scheduled_date.replace(hour=17, minute=45),
            matched_day=None,
            match_reason="",
            avg_hr=132,
            avg_speed=7.2,
            tss=32.0,
        )
        repo.mark_scheduled_session_completed(self.db, session.id)
        return session

    def test_app_routes_expose_overview_calendar_and_evolution(self) -> None:
        session = self._seed_plan()
        repo.add_adaptation_event(
            self.db,
            self.user.id,
            AdaptationLogEntry(
                created_at=None,
                reason_code="logistics_conflict",
                reason_label="Imprevu logistique",
                adaptation_level="micro",
                week_mission_status="unchanged",
                mission_label="Mission inchangée",
                trajectory_impact="low",
                impact_label="Impact faible",
                scenario_type="move",
                mutation_type="move_session",
                summary="Reporter la séance au lendemain.",
                what_changed="Tempo run passe au lendemain.",
                what_protected="la mission de semaine",
                user_message="OK. Je décale.",
                source_text="je peux pas ce soir",
                change_cost=1,
                stability_penalty=5.0,
                protected_session_ids=(),
            ),
        )

        overview = self.client.get("/api/v0/app/overview")
        calendar = self.client.get(f"/api/v0/app/calendar?month={session.scheduled_date.date().isoformat()[:7]}")
        evolution = self.client.get("/api/v0/app/evolution")

        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.json()["lead_session"]["title"], "Tempo run")
        self.assertEqual(overview.json()["lead_session"]["confidence"], "committed")
        self.assertEqual(overview.json()["lead_session"]["role"], "key")
        self.assertIn("planning_contract", overview.json())
        self.assertIn("week_mission", overview.json())
        self.assertIn("calibration_status", overview.json())
        self.assertIn("recent_reality", overview.json())
        self.assertIn("periods", overview.json()["recent_reality"])
        self.assertEqual(overview.json()["last_adaptation"]["mutation_type"], "move_session")
        self.assertEqual(len(overview.json()["recent_adaptations"]), 1)
        self.assertEqual(calendar.status_code, 200)
        self.assertIn("planning_contract", calendar.json())
        self.assertIn("week_mission", calendar.json())
        self.assertIn("calibration_status", calendar.json())
        self.assertTrue(any(item["status"] == "offplan" for item in calendar.json()["feed"]))
        first_session = next(item for item in calendar.json()["feed"] if item["kind"] == "session")
        self.assertEqual(first_session["confidence"], "committed")
        self.assertEqual(first_session["role"], "key")
        self.assertEqual(evolution.status_code, 200)
        self.assertEqual(len(evolution.json()["forecast"]), 4)
        self.assertIn("week_daily", evolution.json())
        self.assertIn("planning_contract", evolution.json())
        self.assertIn("calibration_status", evolution.json())
        self.assertIn("recent_reality", evolution.json())
        self.assertIn("14d", evolution.json()["recent_reality"]["periods"])
        self.assertEqual(evolution.json()["last_adaptation"]["trajectory_impact"], "low")
        self.assertEqual(len(evolution.json()["recent_adaptations"]), 1)

    def test_session_detail_handles_linked_activity_and_coach_block(self) -> None:
        session = self._seed_plan()

        detail = self.client.get(f"/api/v0/sessions/{session.id}")

        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["session"]["status"], "done")
        self.assertEqual(payload["linked_activity"]["title"], "Tempo du jour")
        self.assertEqual(payload["coach"]["goal"], "Tenir l'allure")
        self.assertEqual(payload["content"]["objective"], "Tenir l'allure")
        self.assertEqual(payload["content"]["rationale"], "Reste propre")
        self.assertEqual(payload["content"]["execution"], ["20' tempo"])
        self.assertTrue(payload["content"]["coach_cue"])
        self.assertEqual(len(payload["zone_distribution"]), 5)
