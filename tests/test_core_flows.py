from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-tests-", suffix=".db"))

from fastapi.testclient import TestClient

import fitmas.api_messages as api_messages
import fitmas.calibration_needs as calibration_needs
import fitmas.llm as llm
from fitmas.adaptation import AdaptationResult
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import MutationDecision
from fitmas.plan_actions import move_session
from fitmas.user_indications import (
    IndicationTimeReference,
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
)
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

    def _create_plan_with_tomorrow_session(self) -> tuple[s.WeeklyPlan, s.ScheduledSession]:
        plan, _ = self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        tomorrow = now + timedelta(days=1)
        tomorrow_key = DAY_KEYS[tomorrow.weekday()]
        tomorrow_session = s.ScheduledSession(
            user_id=self.user.id,
            day=tomorrow_key,
            label=day_label_fr(tomorrow_key, capitalize=True),
            scheduled_date=tomorrow.replace(hour=18, minute=0, second=0, microsecond=0),
            source_plan_created_at=now,
            sport_type="running",
            session_type="tempo",
            session_title="Tempo demain",
            session_goal="Stimulus",
            session_note="",
            session_description="50 min",
            duration_min=50,
            intensity="moderate",
            load_score=4,
            priority="Seance cle",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(tomorrow_session)
        self.db.commit()
        self.db.refresh(tomorrow_session)
        return plan, tomorrow_session

    def _seed_uncertain_yesterday_key_session(self) -> tuple[s.WeeklyPlan, s.ScheduledSession]:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        two_days_ago_key = DAY_KEYS[(now.weekday() - 2) % 7]
        plan = repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": two_days_ago_key,
                    "label": day_label_fr(two_days_ago_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "easy",
                    "session_title": "Natation support",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Support",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "cycling",
                    "session_type": "easy",
                    "session_title": "Velo facile",
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
        yesterday_session = s.ScheduledSession(
            user_id=self.user.id,
            day=yesterday_key,
            label=day_label_fr(yesterday_key, capitalize=True),
            scheduled_date=(now - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0),
            sport_type="running",
            session_type="tempo",
            session_title="Course cle hier",
            session_goal="Stimulus",
            session_note="",
            session_description="",
            duration_min=60,
            intensity="moderate",
            load_score=4,
            priority="High",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(yesterday_session)
        self.db.commit()
        self.db.refresh(yesterday_session)
        return plan, yesterday_session

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
            result = self.client.post("/api/v0/messages", json={"text": "Tu peux me simplifier la séance ?"}).json()
            today = self.client.get("/api/v0/today").json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(result["assistant_message"]["text"], "On allège aujourd'hui. Tu récupères.")
        self.assertEqual(today["completion_status"], "adapted")
        self.assertEqual(today["sport_type"], "rest")

    def test_high_impact_replace_session_requires_confirmation_before_apply(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="replace_session",
                target_session_id=session.id,
                new_sport_type="swimming",
                new_session_type="easy",
                new_duration_min=35,
                new_intensity="easy",
                new_title="Natation souple",
                new_goal="Faire tourner sans impact",
                rationale="On bascule sans impact.",
                fitmas_message="Je te bascule la seance en natation souple.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Tu peux remplacer ma seance ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)

        self.assertIn("Tu confirmes", result["assistant_message"]["text"])
        self.assertIsNotNone(refreshed_session)
        self.assertEqual(refreshed_session.sport_type, "running")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "replace_session")

    def test_high_impact_confirmation_yes_applies_pending_mutation(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="replace_session",
                target_session_id=session.id,
                new_sport_type="swimming",
                new_session_type="easy",
                new_duration_min=35,
                new_intensity="easy",
                new_title="Natation souple",
                new_goal="Faire tourner sans impact",
                rationale="On bascule sans impact.",
                fitmas_message="Je te bascule la seance en natation souple.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            first = self.client.post("/api/v0/messages", json={"text": "Tu peux remplacer ma seance ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "oui"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)

        self.assertIn("Tu confirmes", first["assistant_message"]["text"])
        self.assertIsNotNone(refreshed_session)
        self.assertEqual(refreshed_session.sport_type, "swimming")
        self.assertIn("natation", second["assistant_message"]["text"].lower())
        self.assertIsNone(pending)

    def test_high_impact_confirmation_no_keeps_plan_unchanged(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="replace_session",
                target_session_id=session.id,
                new_sport_type="swimming",
                new_session_type="easy",
                new_duration_min=35,
                new_intensity="easy",
                new_title="Natation souple",
                new_goal="Faire tourner sans impact",
                rationale="On bascule sans impact.",
                fitmas_message="Je te bascule la seance en natation souple.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            first = self.client.post("/api/v0/messages", json={"text": "Tu peux remplacer ma seance ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "non"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)

        self.assertIn("Tu confirmes", first["assistant_message"]["text"])
        self.assertIsNotNone(refreshed_session)
        self.assertEqual(refreshed_session.sport_type, "running")
        self.assertIn("Je ne touche pas", second["assistant_message"]["text"])
        self.assertIsNone(pending)

    def test_conversation_turn_records_applied_mutation(self) -> None:
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
            self.client.post("/api/v0/messages", json={"text": "Tu peux me simplifier la séance ?"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].response_mode, "mutation_applied")
        self.assertTrue(turns[0].mutation_applied)
        self.assertEqual(turns[0].mutation_type, "lighten_day")
        self.assertIn('"mutation_type": "lighten_day"', turns[0].decision_json)

    def test_conversation_turn_records_pending_confirmation(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="replace_session",
                target_session_id=session.id,
                new_sport_type="swimming",
                new_session_type="easy",
                new_duration_min=35,
                new_intensity="easy",
                new_title="Natation souple",
                new_goal="Faire tourner sans impact",
                rationale="On bascule sans impact.",
                fitmas_message="Je te bascule la seance en natation souple.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Tu peux remplacer ma seance ?"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].response_mode, "mutation_confirmation")
        self.assertFalse(turns[0].mutation_applied)
        self.assertTrue(turns[0].pending_confirmation)
        self.assertIsNotNone(turns[0].pending_confirmation_id)

    def test_conversation_turn_serializes_datetime_memory_writes(self) -> None:
        row = repo.add_conversation_turn(
            self.db,
            user_id=self.user.id,
            user_message="test",
            assistant_message="ok",
            response_mode="reply",
            extraction_confidence=0.9,
            day_updated=None,
            mutation_type="",
            mutation_applied=False,
            pending_confirmation=False,
            pending_confirmation_id=None,
            decision_json="{}",
            context={"kind": "test"},
            memory_writes=[
                {
                    "category": "execution",
                    "key": "claimed_activity_test",
                    "value": "test",
                    "expires_at": datetime(2026, 4, 2, 7, 30, 0),
                }
            ],
        )

        self.assertIn("2026-04-02T07:30:00", row.memory_writes_json)

    def test_message_flow_can_replan_simple_unavailability_without_llm(self) -> None:
        _, session = self._create_plan_for_today()
        next_day_key = DAY_KEYS[(session.scheduled_date.date().weekday() + 1) % 7]
        self.user.weekly_structure_notes = f"{day_label_fr(next_day_key, capitalize=True)} matin dispo."
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for deterministic unavailability replans")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Merde imprévu je peux pas ce soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=10)
        planned_sessions = [scheduled for scheduled in sessions if scheduled.sport_type != "rest"]
        latest_adaptation = repo.get_latest_adaptation_event(self.db, self.user.id)
        overview = self.client.get("/api/v0/app/overview").json()
        calendar = self.client.get(f"/api/v0/app/calendar?month={session.scheduled_date.date().isoformat()[:7]}").json()

        self.assertIn("Mission hebdo", result["assistant_message"]["text"])
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(planned_sessions), 1)
        self.assertGreater(planned_sessions[0].scheduled_date.date(), session.scheduled_date.date())
        self.assertIsNotNone(latest_adaptation)
        self.assertEqual(latest_adaptation.mutation_type, "move_session")
        self.assertEqual(overview["last_adaptation"]["mutation_type"], "move_session")
        self.assertEqual(overview["last_adaptation"]["adaptation_level"], "micro")
        self.assertTrue(any(item["status"] == "adapted" for item in calendar["feed"]))

    def test_message_flow_can_handle_fatigue_without_llm(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for deterministic fatigue replans")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je suis rincé aujourd'hui, jambes lourdes"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        adapted_session = repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertTrue(result["assistant_message"]["text"].strip())
        self.assertIsNotNone(adapted_session)
        self.assertEqual(adapted_session.completion_status, "adapted")
        self.assertTrue(any(token in adapted_session.session_title.lower() for token in ("version courte", "mobilit", "recup")))

    def test_message_flow_asks_targeted_clarification_before_generic_chat_when_yesterday_changes_week(self) -> None:
        self._seed_uncertain_yesterday_key_session()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run before targeted execution clarification")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertIn("Tu l'as faite ou non", result["assistant_message"]["text"])

    def test_message_flow_blocks_fatigue_adaptation_until_targeted_clarification_is_answered(self) -> None:
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        today_session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(today_session)
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run before targeted execution clarification")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je suis rincé aujourd'hui"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        verify_db = SessionLocal()
        try:
            refreshed_today = repo.get_scheduled_session(verify_db, self.user.id, today_session.id)
            latest_adaptation = repo.get_latest_adaptation_event(verify_db, self.user.id)
        finally:
            verify_db.close()

        self.assertIn("Tu l'as faite ou non", result["assistant_message"]["text"])
        self.assertEqual(refreshed_today.completion_status, "planned")
        self.assertIsNone(latest_adaptation)
        self.assertEqual(yesterday_session.completion_status, "planned")

    def test_contextual_non_answer_resolves_targeted_clarification_without_repeating(self) -> None:
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run when contextual non-completion resolves clarification")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            first = self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "Non"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_yesterday = repo.get_scheduled_session(self.db, self.user.id, yesterday_session.id)
        facts = self.client.get("/api/v0/facts").json()

        self.assertIn("Tu l'as faite ou non", first["assistant_message"]["text"])
        self.assertNotEqual(second["assistant_message"]["text"], first["assistant_message"]["text"])
        self.assertIn("Je ne compte pas", second["assistant_message"]["text"])
        self.assertEqual(refreshed_yesterday.completion_status, "skipped")
        self.assertTrue(any("claimed_non_completion_2026" in fact["key"] for fact in facts if fact["category"] == "execution"))

    def test_health_reply_to_clarification_is_ingested_before_any_repeat(self) -> None:
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run when illness + non-completion resolves clarification")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.check_and_adapt_health_facts = lambda *args, **kwargs: AdaptationResult(
                trigger_type="health_fact",
                message="Repos. Tu es malade, on coupe propre.",
                applied=True,
            )
            first = self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "Je suis malade comme un chien j'ai rien fait"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        self.db.expire_all()
        refreshed_yesterday = repo.get_scheduled_session(self.db, self.user.id, yesterday_session.id)
        facts = self.client.get("/api/v0/facts").json()

        self.assertIn("Tu l'as faite ou non", first["assistant_message"]["text"])
        self.assertNotEqual(second["assistant_message"]["text"], first["assistant_message"]["text"])
        self.assertIn("malade", second["assistant_message"]["text"].lower())
        self.assertEqual(refreshed_yesterday.completion_status, "skipped")
        self.assertTrue(any(fact["category"] == "health" for fact in facts))

    def test_message_flow_can_replan_future_availability_constraint_without_llm(self) -> None:
        _, tomorrow_session = self._create_plan_with_tomorrow_session()
        original_date = tomorrow_session.scheduled_date.date()
        next_open_key = DAY_KEYS[(tomorrow_session.scheduled_date.date().weekday() + 2) % 7]
        self.user.weekly_structure_notes = f"{day_label_fr(next_open_key, capitalize=True)} soir dispo."
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for grounded future availability replans")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je ne suis pas dispo demain soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=10)
        moved_tomorrow_session = next(
            scheduled for scheduled in sessions
            if scheduled.sport_type == "running" and scheduled.session_title == "Tempo demain"
        )

        self.assertIn("Mission hebdo", result["assistant_message"]["text"])
        self.assertGreater(moved_tomorrow_session.scheduled_date.date(), original_date)

    def test_health_indication_can_bypass_decide_and_trigger_protective_reply(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for direct health protection flow")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.check_and_adapt_health_facts = lambda *args, **kwargs: AdaptationResult(
                trigger_type="health_fact",
                message="Je protege l'epaule. Je remplace la prochaine natation par une seance compatible.",
                applied=True,
            )
            result = self.client.post("/api/v0/messages", json={"text": "J'ai mal a l'epaule quand je nage, ca tire"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        facts = self.client.get("/api/v0/facts").json()

        self.assertIn("epaule", result["assistant_message"]["text"].lower())
        self.assertTrue(any(fact["category"] == "health" for fact in facts))

    def test_health_indication_is_not_reprocessed_after_reply(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        call_count = {"health": 0}
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="message libre",
                fitmas_message="Je prends note.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: [
                {
                    "category": "health",
                    "key": "reported_health_shoulder_swimming",
                    "value": "gene a la zone shoulder quand il fait swimming. severite moderate.",
                    "source": "conversation",
                    "confidence": 0.9,
                    "confirmed": True,
                }
            ]

            def fake_health(*args, **kwargs):
                call_count["health"] += 1
                return AdaptationResult(trigger_type="health_fact", message="", applied=False)

            api_messages.check_and_adapt_health_facts = fake_health
            self.client.post("/api/v0/messages", json={"text": "J'ai mal a l'epaule quand je nage, ca tire"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        self.assertEqual(call_count["health"], 1)

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

    def test_current_user_message_is_not_duplicated_in_history_passed_to_llm(self) -> None:
        self._create_plan_for_today()
        captured: dict[str, object] = {}
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(*args, **kwargs):
                captured["conversation_history"] = kwargs.get("conversation_history") or []
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="message libre",
                    fitmas_message="OK.",
                )

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Je voulais te dire ou j'en suis"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(captured["conversation_history"], [])

    def test_low_signal_ack_skips_llm_and_stays_brief(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for low-signal ack")

            api_messages.decide = should_not_run
            result = self.client.post("/api/v0/messages", json={"text": "ok merci"}).json()
        finally:
            api_messages.decide = original_decide

        self.assertEqual(result["assistant_message"]["text"], "Bien recu.")

    def test_week_scope_constraint_uses_real_candidates_in_reply(self) -> None:
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        wednesday = now + timedelta(days=3)
        friday = now + timedelta(days=5)
        for dt, title, sport in (
            (wednesday, "Natation hotel", "swimming"),
            (friday, "Renfo hotel", "strength"),
        ):
            day_key = DAY_KEYS[dt.weekday()]
            self.db.add(
                s.ScheduledSession(
                    user_id=self.user.id,
                    day=day_key,
                    label=day_label_fr(day_key, capitalize=True),
                    scheduled_date=dt.replace(hour=7, minute=0, second=0, microsecond=0),
                    source_plan_created_at=now,
                    sport_type=sport,
                    session_type="easy",
                    session_title=title,
                    session_goal="Support",
                    session_note="",
                    session_description="30 min",
                    duration_min=30,
                    intensity="easy",
                    load_score=2,
                    priority="Normal",
                    nutrition_focus="",
                    flexibility="movable",
                    completion_status="planned",
                )
            )
        self.db.commit()

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for grounded week-scope reply")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
                confidence=0.95,
                source_text="Cette semaine je voyage de mercredi a vendredi",
                scope=UserIndicationScope.WEEK,
                polarity=UserIndicationPolarity.UNAVAILABLE,
                time_reference=IndicationTimeReference(
                    label="mercredi a vendredi",
                    resolved_date=wednesday.date(),
                    day_key=DAY_KEYS[wednesday.weekday()],
                    relative_reference="this_week",
                    window=None,
                ),
            )
            result = self.client.post("/api/v0/messages", json={"text": "Cette semaine je voyage de mercredi a vendredi"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret

        self.assertIn("Natation hotel", result["assistant_message"]["text"])
        self.assertIn("Renfo hotel", result["assistant_message"]["text"])

    def test_future_constraint_without_candidate_stays_honest_and_skips_llm(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run when no session matches the constrained window")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je ne suis pas dispo demain soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertIn("Rien a bouger", result["assistant_message"]["text"])

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

    def test_explicit_non_completion_correction_skips_llm_and_downgrades_unverified_done(self) -> None:
        _, session = self._create_plan_for_today()
        session.scheduled_date = session.scheduled_date - timedelta(days=1)
        session.day = DAY_KEYS[session.scheduled_date.weekday()]
        session.completion_status = "done"
        self.db.commit()

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for explicit non-completion correction")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je n'ai pas couru hier"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        verify_db = SessionLocal()
        try:
            updated = repo.get_scheduled_session(verify_db, self.user.id, session.id)
        finally:
            verify_db.close()

        self.assertIn("Je ne compte pas", result["assistant_message"]["text"])
        self.assertEqual(updated.completion_status, "skipped")

    def test_execution_fact_correction_archives_conflicting_working_memory(self) -> None:
        self._create_plan_for_today()
        yesterday_key = DAY_KEYS[(get_local_now(self.user.timezone).weekday() - 1) % 7]
        skipped_key = f"session_running_{yesterday_key}_skipped"
        completed_key = f"session_running_{yesterday_key}_completed"
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="ok",
                fitmas_message="Bien recu.",
            )

            def fake_extract_facts(user_text: str, assistant_text: str, existing_facts: list[dict]) -> list[dict]:
                lowered = user_text.lower()
                if "n'ai pas couru" in lowered:
                    return [
                        {
                            "category": "execution",
                            "key": skipped_key,
                            "value": f"N'a pas complete la seance de running du {yesterday_key}",
                            "confidence": 0.9,
                            "confirmed": True,
                            "source": "conversation",
                            "action": "upsert",
                        }
                    ]
                if "finalement couru 45 min" in lowered:
                    return [
                        {
                            "category": "execution",
                            "key": completed_key,
                            "value": f"A complete 45min de running {yesterday_key}",
                            "confidence": 0.9,
                            "confirmed": True,
                            "source": "conversation",
                            "action": "upsert",
                        }
                    ]
                return []

            api_messages.extract_facts = fake_extract_facts
            self.client.post("/api/v0/messages", json={"text": "Je n'ai pas couru hier"})
            self.client.post("/api/v0/messages", json={"text": "J'ai finalement couru 45 min hier"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        rows = (
            self.db.query(s.WorkingMemoryEntry)
            .filter(s.WorkingMemoryEntry.category == "execution")
            .order_by(s.WorkingMemoryEntry.id)
            .all()
        )
        active_keys = {row.key for row in rows if row.active}
        archived_keys = {row.key for row in rows if not row.active}

        self.assertIn(completed_key, active_keys)
        self.assertNotIn(skipped_key, active_keys)
        self.assertIn(skipped_key, archived_keys)

    def test_replace_session_reply_is_aligned_with_applied_duration(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="replace_session",
                target_session_id=session.id,
                new_title="Natation recuperation douce",
                new_goal="Repartir souple",
                new_sport_type="swimming",
                new_session_type="recovery",
                new_duration_min=30,
                new_intensity="easy",
                new_description="30 min tres souple",
                rationale="Semaine recente incomplete. On relance sans surcharger.",
                fitmas_message="Je garde la natation mais en recuperation douce 40 min.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "J'ai loupé presque toute la semaine derniere"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        verify_db = SessionLocal()
        try:
            updated = repo.get_scheduled_session(verify_db, self.user.id, session.id)
        finally:
            verify_db.close()

        self.assertEqual(updated.duration_min, 30)
        self.assertIn("30 min", result["assistant_message"]["text"])
        self.assertNotIn("40 min", result["assistant_message"]["text"])

    def test_post_reply_health_adaptation_stays_off_for_non_health_message(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        called = {"health": False}
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="question charge",
                fitmas_message="On repart plus leger.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: [
                {
                    "category": "fatigue",
                    "key": "fatigue_week_missed",
                    "value": "Fatigue percue apres semaine incomplete",
                    "confidence": 0.7,
                    "confirmed": True,
                    "source": "conversation",
                    "affects": ["conversation"],
                    "action": "upsert",
                }
            ]

            def fake_health(*args, **kwargs):
                called["health"] = True
                raise AssertionError("health adaptation should stay off for non-health conversation")

            api_messages.check_and_adapt_health_facts = fake_health
            result = self.client.post("/api/v0/messages", json={"text": "J'ai loupé presque toute la semaine derniere et la tu charges quand meme autant ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        self.assertFalse(called["health"])
        self.assertIn("plus leger", result["assistant_message"]["text"])

    def test_no_change_reply_does_not_promise_unapplied_load_recalibration(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="recalibrage a discuter",
                fitmas_message="On oublie demain, on y va sur 40min technique et dimanche 30min running.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "J'ai loupé presque toute la semaine derniere et la tu charges quand meme autant ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertNotIn("40min", result["assistant_message"]["text"])
        self.assertIn("recalibrer", result["assistant_message"]["text"])

    def test_message_flow_can_consume_hidden_calibration_answer_without_llm(self) -> None:
        self._create_plan_for_today()
        need = calibration_needs.CalibrationNeed(
            id="availability_window:availability:thursday",
            need_type=calibration_needs.CalibrationNeedType.AVAILABILITY_WINDOW,
            topic="availability:thursday",
            status=calibration_needs.CalibrationNeedStatus.OPEN,
            why_now="test",
            priority=calibration_needs.CalibrationNeedPriority.MEDIUM,
            source="heartbeat_morning",
            channel_hint="telegram",
            created_at="2026-03-29T08:00+00:00",
            expires_at="2026-04-03T08:00+00:00",
            last_prompted_at="2026-03-29T08:00+00:00",
            context={"day": "thursday", "day_label": "jeudi", "session_id": 12, "session_title": "Tempo"},
            allowed_answers=("morning", "evening", "both", "none"),
            write_targets=("working_memory.availability",),
        )
        repo.upsert_working_memory(self.db, self.user.id, [need.as_memory_update()])
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for standalone calibration answers")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Plutot le soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        facts = self.client.get("/api/v0/facts").json()
        categories = {(fact["category"], fact["key"]) for fact in facts}

        self.assertTrue(result["assistant_message"]["text"].strip())
        self.assertIn("jeudi", result["assistant_message"]["text"].lower())
        self.assertIn(("availability", "weekly_slot_thursday"), categories)
        self.assertNotIn(("calibration_need", "availability:thursday"), categories)

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
