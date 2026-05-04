from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-heartbeat-debug-", suffix=".db"))
os.environ["FITMAS_ENABLE_DEBUG_ENDPOINTS"] = "1"

from fastapi.testclient import TestClient

import fitmas.heartbeat as heartbeat
from fitmas import repository as repo, schema as s
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class HeartbeatDebugEndpointTest(unittest.TestCase):
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
            coach_name="FitMAS",
            coach_style="direct",
            primary_objective="10km propre",
            objective="10km propre",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        heartbeat._LAST_PROACTIVE_GUARD_AT.clear()

    def tearDown(self) -> None:
        self.db.close()
        heartbeat._LAST_PROACTIVE_GUARD_AT.clear()

    def _create_today_plan(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="debug heartbeat",
            summary="debug",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing hier",
                    "session_goal": "Base",
                    "session_note": "",
                    "session_description": "35 min",
                    "duration_min": 35,
                    "intensity": "easy",
                    "load_score": 2,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing facile",
                    "session_goal": "Reprendre propre",
                    "session_note": "",
                    "session_description": "40 min",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 2,
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
            title="Footing tronque",
            duration_min=12,
            distance_m=1800,
            elevation_m=0,
            perceived_load=2,
            note="fatigue",
            started_at=now - timedelta(days=1),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=8.0,
        )

    def test_debug_dump_exposes_prompt_raw_llm_judge_and_final_decision(self) -> None:
        self._create_today_plan()
        original_generate = heartbeat.generate_heartbeat_text_with_debug
        original_request_text = heartbeat.request_text
        try:
            heartbeat.generate_heartbeat_text_with_debug = lambda *args, **kwargs: {
                "raw_text": "Regarde ton app demain matin, j'ai ajuste le planning.",
                "text": "Regarde ton app demain matin, j'ai ajuste le planning.",
                "reason": "generated",
                "allow_no_send": kwargs.get("allow_no_send", True),
            }
            heartbeat.request_text = lambda **kwargs: "BLOCK"
            response = self.client.post("/api/v0/debug/heartbeat/morning?dump=true&send=false")
        finally:
            heartbeat.generate_heartbeat_text_with_debug = original_generate
            heartbeat.request_text = original_request_text

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["kind"], "morning")
        self.assertTrue(payload["triggered"])
        self.assertFalse(payload["sent"])
        debug = payload["debug"]
        self.assertEqual(debug["kind"], "morning")
        self.assertEqual(debug["pipeline"], "heartbeat_briefing")
        self.assertIn("[TodayTruth", debug["prompt"]["user"])
        self.assertIn("Voix coach", debug["prompt"]["system"])
        self.assertEqual(debug["llm"]["raw_text"], "Regarde ton app demain matin, j'ai ajuste le planning.")
        self.assertEqual(debug["judge"]["decision"], "BLOCK")
        self.assertTrue(debug["judge"]["blocked"])
        self.assertEqual(debug["decision"]["action"], "send")
        self.assertEqual(debug["decision"]["reason"], "fallback_after_llm_no_message")
        self.assertEqual(debug["final"]["message"], payload["message"])

    def test_debug_dump_reports_no_send_reason_when_gate_or_context_skips(self) -> None:
        response = self.client.post("/api/v0/debug/heartbeat/morning?dump=true&send=false")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["triggered"])
        debug = payload["debug"]
        self.assertEqual(debug["kind"], "morning")
        self.assertEqual(debug["decision"]["action"], "no_send")
        self.assertEqual(debug["decision"]["reason"], "no_today_session")
        self.assertIsNone(debug["final"]["message"])


if __name__ == "__main__":
    unittest.main()
