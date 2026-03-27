from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-tests-", suffix=".db"))

from fastapi.testclient import TestClient

import fitmas.api_messages as api_messages
import fitmas.llm as llm
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

    def test_read_models_expose_load_band_and_week_meta(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=self.user.timezone,
            mesocycle_week=4,
            mesocycle_number=2,
            total_weeks=8,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "intervals",
                    "session_title": "Fractionne court",
                    "session_goal": "Stimulus",
                    "session_note": "propre",
                    "session_description": "8 x 400m",
                    "duration_min": 50,
                    "intensity": "hard",
                    "load_score": 4,
                    "priority": "Seance cle",
                    "nutrition_focus": "Hydratation",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )

        week = self.client.get("/api/v0/week")
        today = self.client.get("/api/v0/today")
        timeline = self.client.get("/api/v0/timeline")

        self.assertEqual(week.status_code, 200)
        self.assertEqual(week.json()["total_weeks"], 8)
        self.assertEqual(week.json()["mesocycle_week"], 4)
        self.assertTrue(week.json()["is_deload"])
        self.assertEqual(week.json()["days"][0]["load_band"], "hard")

        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["load_band"], "hard")

        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()[0]["load_band"], "hard")

    def test_performance_overview_exposes_tss_and_distribution(self) -> None:
        _, session = self._create_plan_for_today()
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            scheduled_session_id=session.id,
            sport_type="running",
            title="Footing du jour",
            duration_min=38,
            distance_m=7200,
            elevation_m=32,
            perceived_load=2,
            note="ok",
            started_at=session.scheduled_date.replace(hour=7, minute=30),
            matched_day=session.day,
            match_reason="manual test",
            avg_hr=141,
            avg_speed=3.15,
            tss=28.0,
        )
        repo.mark_scheduled_session_completed(self.db, session.id)

        overview = self.client.get("/api/v0/stats/performance-overview")

        self.assertEqual(overview.status_code, 200)
        payload = overview.json()
        self.assertIn("tss", payload)
        self.assertIn("load", payload)
        self.assertIn("distribution", payload)
        self.assertGreater(payload["tss"]["target"], 0)
        self.assertGreater(payload["tss"]["actual"], 0)
        self.assertEqual(payload["distribution"]["planned"]["easy"]["count"], 1)
        self.assertEqual(payload["distribution"]["completed"]["easy"]["count"], 1)

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

    def test_message_flow_passes_grounding_context_to_llm(self) -> None:
        _, session = self._create_plan_for_today()
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="cycling",
            title="Velo off-plan",
            duration_min=75,
            distance_m=16000,
            elevation_m=80,
            perceived_load=3,
            note="",
            started_at=session.scheduled_date.replace(hour=18),
            matched_day=None,
            match_reason="",
            avg_hr=156,
            avg_speed=6.0,
            tss=28.0,
        )
        captured: dict[str, str] = {}
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(*args, **kwargs):
                captured["execution_summary"] = kwargs.get("execution_summary") or ""
                captured["temporal_summary"] = kwargs.get("temporal_summary") or ""
                captured["activity_claim_summary"] = kwargs.get("activity_claim_summary") or ""
                captured["signal_summary"] = kwargs.get("signal_summary") or ""
                captured["selected_facts"] = "\n".join(kwargs.get("coach_context", {}).get("selected_facts", []))
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="ok",
                    fitmas_message="Bien recu.",
                )

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "J'ai couru aujourd'hui 30 min"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertIn("execution_status: off_plan_done", captured["execution_summary"])
        self.assertIn("reference principale: today", captured["temporal_summary"])
        self.assertIn("sport: running", captured["activity_claim_summary"])
        self.assertIn("duree_min: 30", captured["activity_claim_summary"])
        self.assertIn("big_session_done", captured["signal_summary"])
        self.assertIn("Activite declaree par l'utilisateur", captured["selected_facts"])

    def test_message_flow_persists_unlogged_activity_claim_fact(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="ok",
                fitmas_message="Bien recu.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "J'ai couru aujourd'hui 30 min"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        facts = self.client.get("/api/v0/facts").json()

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["category"], "execution")
        self.assertEqual(facts[0]["ttl"], "immediate")
        self.assertIn("30 min", facts[0]["value"])

    def test_message_flow_archives_superseded_claim_after_temporal_correction(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="ok",
                fitmas_message="Bien recu.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "J'ai couru aujourd'hui 30 min"})
            self.client.post("/api/v0/messages", json={"text": "Non c'etait hier"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        facts = self.client.get("/api/v0/facts").json()

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["category"], "execution")
        self.assertIn("2026-", facts[0]["key"])
        self.assertIn("running", facts[0]["key"])
        self.assertIn("30 min", facts[0]["value"])

    def test_message_flow_can_answer_read_query_via_tool(self) -> None:
        _, session = self._create_plan_for_today()
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="cycling",
            title="Velo long",
            duration_min=90,
            distance_m=36000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=session.scheduled_date.replace(hour=18),
            matched_day=None,
            match_reason="",
            avg_hr=145,
            avg_speed=8.2,
            tss=55.0,
        )
        original_client = llm._client
        original_request_message = llm._request_message
        original_extract_facts = api_messages.extract_facts
        calls = {"count": 0}
        try:
            def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
                calls["count"] += 1
                if calls["count"] == 1:
                    return SimpleNamespace(
                        stop_reason="tool_use",
                        content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_activity_highlights", input={"days": 30})],
                        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
                    )
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[
                        SimpleNamespace(
                            type="text",
                            text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"lecture outil","fitmas_message":"Ta plus longue sortie recente est Velo long 90 min."}',
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=180, output_tokens=35),
                )

            llm._client = lambda: object()
            llm._request_message = fake_request_message
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "C'etait quoi ma plus longue sortie recente ?"}).json()
        finally:
            llm._client = original_client
            llm._request_message = original_request_message
            api_messages.extract_facts = original_extract_facts

        self.assertIn("Velo long 90 min", result["assistant_message"]["text"])
        self.assertGreaterEqual(calls["count"], 2)

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

    def test_today_view_exposes_fitness_and_recent_same_sport_activity(self) -> None:
        _, session = self._create_plan_for_today()
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="running",
            title="Footing repere",
            duration_min=48,
            distance_m=9200,
            elevation_m=80,
            perceived_load=3,
            note="propre",
            started_at=session.scheduled_date - timedelta(days=3),
            matched_day=None,
            match_reason="",
            avg_hr=148,
            avg_speed=3.35,
            tss=44.0,
        )

        today = self.client.get("/api/v0/today").json()

        self.assertIn("fitness", today)
        self.assertIn("recent_activity", today)
        self.assertEqual(today["recent_activity"]["title"], "Footing repere")
        self.assertGreaterEqual(today["fitness"]["ctl"], 0)


if __name__ == "__main__":
    unittest.main()
