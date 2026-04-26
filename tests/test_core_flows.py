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
import fitmas.conversation_pipeline as conversation_pipeline
import fitmas.llm as llm
from fitmas.adaptation import AdaptationResult
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import CoachDecision, MutationDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
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
        self._original_plan_conversation_turn = api_messages.plan_conversation_turn
        api_messages.plan_conversation_turn = lambda *args, **kwargs: None

    def tearDown(self) -> None:
        api_messages.plan_conversation_turn = self._original_plan_conversation_turn
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
        self.db.query(s.CoachMessage).delete()
        self.db.query(s.ConversationTurnRecord).delete()
        self.db.query(s.UserFact).delete()
        self.db.commit()
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
        self.assertEqual(week.json()["runtime_role"], "template_compat")
        self.assertEqual(week.json()["total_weeks"], 8)
        self.assertEqual(week.json()["mesocycle_week"], 4)
        self.assertTrue(week.json()["is_deload"])
        self.assertEqual(week.json()["days"][0]["load_band"], "hard")

        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["load_band"], "hard")

        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()[0]["load_band"], "hard")

    def test_today_by_day_does_not_fall_back_to_legacy_day_plan(self) -> None:
        _, session = self._create_plan_for_today()
        today_key = session.day

        self.db.delete(session)
        self.db.commit()

        response = self.client.get(f"/api/v0/today/{today_key}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], f"No scheduled session found for {today_key}")

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

    def test_message_flow_applies_valid_coach_decision_plan_patch(self) -> None:
        target_date = "2099-04-29"
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="plan_patch",
                rationale="piscine fermee, on garde une charge facile",
                fitmas_message="Je pose un footing easy mercredi.",
                plan_patch=PlanPatch(
                    coach_message="Je pose un footing easy mercredi.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="create_session",
                            target_date=target_date,
                            new_sport_type="running",
                            new_session_type="easy",
                            new_title="Footing easy",
                            new_duration_min=30,
                            rationale="Remplacement conservateur sans piscine.",
                        )
                    ],
                ),
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Piscine fermee, mets du running"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=20)
        events = (
            self.db.query(s.PlanMutationEventRecord)
            .filter(s.PlanMutationEventRecord.user_id == self.user.id)
            .order_by(s.PlanMutationEventRecord.id.desc())
            .all()
        )

        self.assertEqual(result["assistant_message"]["text"], "Je pose un footing easy mercredi.")
        self.assertTrue(any(session.sport_type == "running" and session.duration_min == 30 for session in sessions))
        self.assertEqual(events[0].command_type, "create_session")
        self.assertEqual(events[0].user_visible_summary, "Je pose un footing easy mercredi.")

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

    def test_plan_patch_requiring_confirmation_serializes_pending_and_applies_on_yes(self) -> None:
        _, session = self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        for offset in (2, 3, 4):
            day = now + timedelta(days=offset)
            hard_session = s.ScheduledSession(
                user_id=self.user.id,
                day=DAY_KEYS[day.weekday()],
                label=day_label_fr(DAY_KEYS[day.weekday()], capitalize=True),
                scheduled_date=day.replace(hour=18, minute=0, second=0, microsecond=0),
                sport_type="running",
                session_type="intervals",
                session_title=f"Hard {offset}",
                session_goal="Stimulus",
                duration_min=50,
                intensity="hard",
                load_score=4,
                priority="Seance cle",
                flexibility="stable",
                completion_status="planned",
            )
            self.db.add(hard_session)
        self.db.commit()

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="plan_patch",
                rationale="Le user veut forcer une seance dure.",
                fitmas_message="Je peux le faire, mais ca charge la semaine.",
                plan_patch=PlanPatch(
                    coach_message="Je remplace par un tempo dur.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="replace_session",
                            target_session_id=session.id,
                            new_sport_type="running",
                            new_session_type="tempo",
                            new_title="Tempo dur",
                            new_duration_min=45,
                            new_intensity="hard",
                            rationale="Preference utilisateur confirmee.",
                        )
                    ],
                ),
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            first = self.client.post("/api/v0/messages", json={"text": "Mets une seance dure a la place"}).json()
            pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)
            second = self.client.post("/api/v0/messages", json={"text": "oui"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        active_pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)
        events = (
            self.db.query(s.PlanMutationEventRecord)
            .filter(s.PlanMutationEventRecord.user_id == self.user.id)
            .order_by(s.PlanMutationEventRecord.id.desc())
            .all()
        )

        self.assertIn("Tu confirmes", first["assistant_message"]["text"])
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "plan_patch")
        self.assertIn('"kind": "plan_patch"', pending.decision_json)
        self.assertIsNotNone(refreshed_session)
        self.assertEqual(refreshed_session.session_title, "Tempo dur")
        self.assertEqual(refreshed_session.intensity, "hard")
        self.assertIn("tempo", second["assistant_message"]["text"].lower())
        self.assertIsNone(active_pending)
        self.assertEqual(events[0].command_type, "replace_session")

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

    def test_conversation_turn_records_no_change_as_not_applied(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="lecture seule",
                fitmas_message="Je regarde sans toucher au plan.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Tu vois quoi aujourd'hui ?"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].mutation_type, "no_change")
        self.assertFalse(turns[0].mutation_applied)

    def test_blocked_mutation_does_not_reply_as_applied(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_apply = conversation_pipeline.apply_decisions_for_user
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="move_session",
                target_session_id=session.id,
                target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                rationale="unsafe move",
                fitmas_message="OK. Je deplace la seance demain.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            conversation_pipeline.apply_decisions_for_user = lambda *args, **kwargs: SimpleNamespace(
                applied_count=0,
                event_count=0,
                applied_events=(),
            )
            result = self.client.post("/api/v0/messages", json={"text": "Mets ca demain"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            conversation_pipeline.apply_decisions_for_user = original_apply

        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertNotIn("OK. Je deplace", result["assistant_message"]["text"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].mutation_type, "move_session")
        self.assertFalse(turns[0].mutation_applied)

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
            # Chantier 1 (autonomy refactor): decide() must run on every
            # conversational turn. When the LLM returns None the deterministic
            # adaptation falls back to apply, so the data outcome is unchanged.
            api_messages.decide = lambda *args, **kwargs: None
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

        self.assertIn("Le cap de la semaine ne bouge pas", result["assistant_message"]["text"])
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
            # Chantier 1 (autonomy refactor): decide() must run on every
            # conversational turn. With the LLM returning None the deterministic
            # fatigue adaptation falls back to apply unchanged.
            api_messages.decide = lambda *args, **kwargs: None
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
        normalized_title = api_messages._normalize_text(adapted_session.session_title)
        self.assertTrue(any(token in normalized_title for token in ("version courte", "mobilit", "recup")))
        events = self.db.query(s.PlanMutationEventRecord).all()
        self.assertEqual(len(events), 1)
        self.assertIn(events[0].trigger_type, {"health_adaptation", "life_change_adaptation"})

    def test_message_flow_surfaces_targeted_clarification_as_prompt_context_to_llm(self) -> None:
        """Chantier 3bis (autonomy refactor): the targeted execution
        clarification no longer short-circuits the pipeline with a canned
        "Tu l'as faite ou pas ?" reply (which looped on missed sessions).
        It is surfaced as soft prompt context — the LLM arbitrates whether
        to ask, integrate or move on."""
        self._seed_uncertain_yesterday_key_session()
        captured: dict[str, object] = {}
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(*args, **kwargs):
                captured["unresolved_followup"] = (
                    kwargs.get("coach_context", {}).get("unresolved_execution_followup")
                )
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="J'ai vu hier flou, je decide moi-meme.",
                    fitmas_message="Aujourd'hui on tient le plan. Tu m'as pas dit pour hier — je tablerai sur seance manquee si tu ne corriges pas.",
                )

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(result["assistant_message"]["text"], "Aujourd'hui on tient le plan. Tu m'as pas dit pour hier — je tablerai sur seance manquee si tu ne corriges pas.")
        followup = captured.get("unresolved_followup") or ""
        self.assertIn("Suivi execution non resolu", followup)
        self.assertIn("Tu l'as faite ou pas", followup)

    def test_targeted_clarification_does_not_block_fatigue_adaptation_anymore(self) -> None:
        """Chantier 3bis: the canned clarification used to swallow the
        fatigue request. It must now coexist as soft context — decide() runs
        and can apply the deterministic fatigue adaptation."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        today_session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(today_session)
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: None  # let deterministic adaptation fall back
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

        self.assertTrue(result["assistant_message"]["text"].strip())
        self.assertEqual(refreshed_today.completion_status, "adapted")
        self.assertIsNotNone(latest_adaptation)

    def test_targeted_clarification_followup_breaks_loop_after_first_turn(self) -> None:
        """Chantier 3bis: anti-loop guard — once the LLM asked the
        clarification last turn, the soft followup block must not be
        re-injected on the next turn (regardless of how the user answered).
        Otherwise the coach loops on missed sessions."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        captured_followups: list[str | None] = []
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(*args, **kwargs):
                captured_followups.append(
                    kwargs.get("coach_context", {}).get("unresolved_execution_followup")
                )
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Reponse coach.",
                    fitmas_message="Tu l'as faite ou pas hier ?",
                )

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            self.client.post("/api/v0/messages", json={"text": "Non"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(len(captured_followups), 2)
        self.assertIsNotNone(captured_followups[0])
        self.assertIn("Suivi execution non resolu", captured_followups[0] or "")
        # Anti-loop guard: previous_agent_text already contained the canned
        # phrasing, so the helper returns None and no block is injected.
        self.assertIsNone(captured_followups[1])

    def test_contextual_non_answer_resolves_clarification_via_decide(self) -> None:
        """Chantier 3bis: when the LLM picks up the soft followup context
        and asks the question itself, a "Non" on the next turn must still
        resolve the session as skipped via execution contestation."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        replies = iter([
            # Turn 1: LLM uses the soft followup and asks the question.
            "Avant que je tranche pour aujourd'hui — tu l'as faite ou pas hier ?",
            # Turn 2: LLM acknowledges non-completion.
            "Bien note. Je ne compte pas cette seance comme faite.",
        ])
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="Reponse a la clarification.",
                fitmas_message=next(replies),
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "Non"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_yesterday = repo.get_scheduled_session(self.db, self.user.id, yesterday_session.id)
        facts = self.client.get("/api/v0/facts").json()

        self.assertIn("Je ne compte pas", second["assistant_message"]["text"])
        self.assertEqual(refreshed_yesterday.completion_status, "skipped")
        self.assertTrue(any("claimed_non_completion_2026" in fact["key"] for fact in facts if fact["category"] == "execution"))

    def test_health_reply_after_clarification_is_ingested_normally(self) -> None:
        """Chantier 3bis: an illness reply on the second turn must still
        route through the health adaptation flow without the canned
        clarification reasserting itself."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        original_interpret = api_messages.interpret_user_indication
        try:
            def fake_decide(user_text, *args, **kwargs):
                if "malade" in user_text:
                    return MutationDecision(
                        mutation_type="no_change",
                        rationale="Maladie signalee, le coach arbitre sans fallback deterministe.",
                        fitmas_message="Tu es malade, donc on ne force rien aujourd'hui.",
                    )
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Premier tour, je pose la question.",
                    fitmas_message="Avant de trancher pour aujourd'hui — tu l'as faite ou pas hier ?",
                )

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.check_and_adapt_health_facts = lambda *args, **kwargs: AdaptationResult(
                trigger_type="health_fact",
                message="Repos. Tu es malade, on coupe propre.",
                applied=True,
            )
            api_messages.interpret_user_indication = lambda text, **kwargs: (
                UserIndication(
                    kind=UserIndicationKind.HEALTH_SIGNAL,
                    confidence=0.95,
                    source_text=text,
                    scope=UserIndicationScope.SINGLE_DAY,
                    polarity=UserIndicationPolarity.SIGNAL,
                    time_reference=IndicationTimeReference(
                        label="hier",
                        resolved_date=yesterday_session.scheduled_date.date(),
                        day_key=yesterday_session.day,
                        relative_reference="yesterday",
                        window=None,
                    ),
                    body_zone="general",
                    trigger_activity="general",
                    symptom_type="illness",
                    execution_sport_type=yesterday_session.sport_type,
                    execution_completed=False,
                )
                if "malade" in text
                else None
            )
            self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "Je suis malade comme un chien j'ai rien fait"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health
            api_messages.interpret_user_indication = original_interpret

        self.db.expire_all()
        refreshed_yesterday = repo.get_scheduled_session(self.db, self.user.id, yesterday_session.id)
        facts = self.client.get("/api/v0/facts").json()

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
            # Chantier 1 (autonomy refactor): decide() must run on every
            # conversational turn. The deterministic future-availability
            # adaptation falls back when the LLM returns None.
            api_messages.decide = lambda *args, **kwargs: None
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

        self.assertIn("Le cap de la semaine ne bouge pas", result["assistant_message"]["text"])
        self.assertGreater(moved_tomorrow_session.scheduled_date.date(), original_date)

    def test_grounded_availability_adaptation_routes_candidate_to_llm(self) -> None:
        _, tomorrow_session = self._create_plan_with_tomorrow_session()
        original_date = tomorrow_session.scheduled_date.date()
        next_open_key = DAY_KEYS[(tomorrow_session.scheduled_date.date().weekday() + 2) % 7]
        self.user.weekly_structure_notes = f"{day_label_fr(next_open_key, capitalize=True)} soir dispo."
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, str] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="availability_constraint",
                secondary_intents=(),
                has_plan_mutation=False,
                model_dump=lambda mode="json": {
                    "primary_intent": "availability_constraint",
                    "secondary_intents": [],
                    "has_plan_mutation": False,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["temporal_summary"] = kwargs.get("temporal_summary") or ""
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Le LLM arbitre la candidate deterministe.",
                    fitmas_message="Je vois une option de report, tu confirmes ?",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "Je ne suis pas dispo demain soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

        self.db.expire_all()
        unchanged_session = repo.get_scheduled_session(self.db, self.user.id, tomorrow_session.id)
        self.assertEqual(result["assistant_message"]["text"], "Je vois une option de report, tu confirmes ?")
        self.assertEqual(unchanged_session.scheduled_date.date(), original_date)
        self.assertIn("Adaptation candidate", captured["temporal_summary"])

    def test_health_indication_reaches_decide_before_protective_fallback(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        decide_calls = {"count": 0}
        try:
            def fake_decide(*args, **kwargs):
                decide_calls["count"] += 1
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Signal sante arbitre par le coach.",
                    fitmas_message="Je prends l'epaule au serieux avant de toucher au plan.",
                )

            api_messages.decide = fake_decide
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

        self.assertEqual(decide_calls["count"], 1)
        self.assertIn("epaule", result["assistant_message"]["text"].lower())
        self.assertTrue(any(fact["category"] == "health" for fact in facts))

    def test_health_adaptation_suggestion_requires_confirmation(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        decide_calls = {"count": 0}
        try:
            def fake_decide(*args, **kwargs):
                decide_calls["count"] += 1
                return None

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.check_and_adapt_health_facts = lambda *args, **kwargs: AdaptationResult(
                trigger_type="health_fact",
                decisions=[
                    MutationDecision(
                        mutation_type="replace_session",
                        target_session_id=session.id,
                        new_sport_type="strength",
                        new_session_type="mobility",
                        new_title="Mobilite epaule",
                        rationale="Douleur epaule signalee.",
                        fitmas_message="Je protegerais l'epaule avec une seance compatible.",
                    )
                ],
                message="Je protegerais l'epaule avec une seance compatible.",
                applied=False,
            )
            result = self.client.post("/api/v0/messages", json={"text": "J'ai mal a l'epaule quand je nage, ca tire"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)

        self.assertEqual(decide_calls["count"], 1)
        self.assertIsNotNone(pending)
        self.assertIn("confirmes", result["assistant_message"]["text"].lower())
        self.assertEqual(pending.mutation_type, "replace_session")
        self.assertEqual(pending.status, "pending")

    def test_compound_health_and_plan_mutation_reaches_llm_before_health_adaptation(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []

            def should_not_run_health(*args, **kwargs):
                raise AssertionError("health adaptation should not run before LLM on compound mutation turns")

            api_messages.check_and_adapt_health_facts = should_not_run_health
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.HEALTH_SIGNAL,
                confidence=0.95,
                source_text="J'ai mal a l'epaule quand je nage, mets piscine vendredi a la place",
                scope=UserIndicationScope.SINGLE_DAY,
                polarity=UserIndicationPolarity.SIGNAL,
                body_zone="shoulder",
                trigger_activity="swimming",
                symptom_type="pain",
                health_severity=None,
            )
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="plan_mutation",
                secondary_intents=("health_signal",),
                has_plan_mutation=True,
                model_dump=lambda mode="json": {
                    "primary_intent": "plan_mutation",
                    "secondary_intents": ["health_signal"],
                    "has_plan_mutation": True,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["selected_facts"] = kwargs.get("coach_context", {}).get("selected_facts", [])
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Signal sante + demande de mutation a arbitrer ensemble.",
                    fitmas_message="Je tiens compte de l'epaule avant de bouger la piscine.",
                )

            api_messages.decide = fake_decide
            result = self.client.post(
                "/api/v0/messages",
                json={"text": "J'ai mal a l'épaule quand je nage, mets piscine vendredi à la place"},
            ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        facts = self.client.get("/api/v0/facts").json()
        self.assertEqual(result["assistant_message"]["text"], "Je tiens compte de l'epaule avant de bouger la piscine.")
        self.assertEqual(updated.completion_status, "planned")
        self.assertTrue(any(fact["category"] == "health" for fact in facts))
        self.assertTrue(any("epaule" in str(fact).lower() or "shoulder" in str(fact).lower() for fact in captured["selected_facts"]))

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

    def test_low_signal_ack_routes_label_context_to_llm(self) -> None:
        """Chantier 1 (autonomy refactor): low-signal acks no longer
        short-circuit decide() with a templated reply. The classifier
        produces a label that is injected as prompt context, and the LLM
        arbitrates a short, plain answer.
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        captured: dict[str, str] = {}
        try:
            def fake_decide(*args, **kwargs):
                captured["temporal_summary"] = kwargs.get("temporal_summary") or ""
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Ack pur, pas de mutation.",
                    fitmas_message="Bien recu.",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "ok merci"}).json()
        finally:
            api_messages.decide = original_decide

        self.assertEqual(result["assistant_message"]["text"], "Bien recu.")
        self.assertIn("low-signal", captured["temporal_summary"])

    def test_claim_without_mutation_is_demoted_at_pipeline_egress(self) -> None:
        """Chantier 1bis (anti-mensonge "dire = faire"): si le LLM affirme
        une action ("Je libere ce creneau") sans qu'aucune mutation ne soit
        committee ce tour, la reponse doit etre reecrite en demande de
        clarification explicite.
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        try:
            def fake_decide(*args, **kwargs):
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Phantom action emise par le LLM.",
                    fitmas_message="OK. Je libere ce creneau et je garde la suite propre.",
                )

            api_messages.decide = fake_decide
            result = self.client.post(
                "/api/v0/messages", json={"text": "Mercredi"}
            ).json()
        finally:
            api_messages.decide = original_decide

        text = result["assistant_message"]["text"]
        self.assertNotIn("Je libere", text)
        self.assertIn("n'ai applique aucun changement", text)

    def test_neutral_reply_with_no_mutation_passes_through(self) -> None:
        """Le garde dire=faire ne doit toucher que les reponses qui affirment
        une action mutationnelle. Une reponse neutre passe sans modification.
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        try:
            def fake_decide(*args, **kwargs):
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Question simple, pas de mutation.",
                    fitmas_message="Bien recu, je note.",
                )

            api_messages.decide = fake_decide
            result = self.client.post(
                "/api/v0/messages", json={"text": "ok"}
            ).json()
        finally:
            api_messages.decide = original_decide

        text = result["assistant_message"]["text"]
        self.assertEqual(text, "Bien recu, je note.")
        self.assertNotIn("n'ai applique aucun changement", text)

    def test_week_scope_constraint_routes_grounded_context_to_llm(self) -> None:
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
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, str] = {}
        try:
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
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="availability_constraint",
                secondary_intents=(),
                has_plan_mutation=False,
                model_dump=lambda mode="json": {
                    "primary_intent": "availability_constraint",
                    "secondary_intents": [],
                    "has_plan_mutation": False,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["signal_summary"] = kwargs.get("signal_summary") or ""
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Contrainte large, besoin confirmation.",
                    fitmas_message="Je vois les seances touchees. Tu confirmes off complet ?",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "Cette semaine je voyage de mercredi a vendredi"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertEqual(result["assistant_message"]["text"], "Je vois les seances touchees. Tu confirmes off complet ?")
        self.assertIn("Natation hotel", captured["signal_summary"])
        self.assertIn("Renfo hotel", captured["signal_summary"])
        self.assertNotIn("this_week", captured["signal_summary"])

    def test_week_scope_grounding_never_exposes_internal_reference_labels(self) -> None:
        indication = UserIndication(
            kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
            confidence=0.95,
            source_text="Cette semaine je voyage",
            scope=UserIndicationScope.WEEK,
            polarity=UserIndicationPolarity.UNAVAILABLE,
            time_reference=IndicationTimeReference(
                label="this_week",
                resolved_date=get_local_now(self.user.timezone).date(),
                day_key=None,
                relative_reference="this_week",
                window=None,
            ),
        )
        resolution = SimpleNamespace(
            reference_label="this_week",
            matched_session_id=None,
            candidate_sessions=[],
        )

        reply = api_messages._week_scope_reply(indication, resolution)

        self.assertIsNotNone(reply)
        self.assertNotIn("this_week", reply)
        self.assertIn("cette semaine", reply.lower())

    def test_swap_wording_bypasses_availability_week_scope_reply(self) -> None:
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        wednesday = now + timedelta(days=(2 - now.weekday()) % 7)
        thursday = now + timedelta(days=(3 - now.weekday()) % 7)
        renfo = s.ScheduledSession(
            user_id=self.user.id,
            day=DAY_KEYS[wednesday.weekday()],
            label=day_label_fr(DAY_KEYS[wednesday.weekday()], capitalize=True),
            scheduled_date=wednesday.replace(hour=7, minute=0, second=0, microsecond=0),
            sport_type="strength",
            session_type="general",
            session_title="Renfo general",
            session_goal="Socle",
            session_note="",
            session_description="36 min",
            duration_min=36,
            intensity="moderate",
            load_score=2,
            priority="Support",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        swim = s.ScheduledSession(
            user_id=self.user.id,
            day=DAY_KEYS[thursday.weekday()],
            label=day_label_fr(DAY_KEYS[thursday.weekday()], capitalize=True),
            scheduled_date=thursday.replace(hour=7, minute=0, second=0, microsecond=0),
            sport_type="swimming",
            session_type="css",
            session_title="Natation CSS",
            session_goal="Seuil",
            session_note="",
            session_description="40 min",
            duration_min=40,
            intensity="moderate",
            load_score=3,
            priority="Support",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add_all([renfo, swim])
        self.db.commit()
        self.db.refresh(renfo)
        self.db.refresh(swim)

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
                confidence=0.95,
                source_text="On peut echanger mercredi et jeudi ?",
                scope=UserIndicationScope.WEEK,
                polarity=UserIndicationPolarity.UNAVAILABLE,
                time_reference=IndicationTimeReference(
                    label="mercredi et jeudi",
                    resolved_date=wednesday.date(),
                    day_key=DAY_KEYS[wednesday.weekday()],
                    relative_reference="this_week",
                    window=None,
                ),
            )

            def fake_decide(*args, **kwargs):
                return MutationDecision(
                    mutation_type="swap_sessions",
                    target_session_id=renfo.id,
                    second_session_id=swim.id,
                    rationale="Echange mercredi et jeudi.",
                    fitmas_message="Je peux echanger mercredi et jeudi.",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "On peut échanger mercredi et jeudi ?"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret

        self.assertNotIn("off complet", result["assistant_message"]["text"].lower())
        self.assertIn("echanger", result["assistant_message"]["text"].lower())
        self.assertIn("confirmes", result["assistant_message"]["text"].lower())

    def test_compound_non_completion_swap_reaches_llm_before_skip(self) -> None:
        now = get_local_now(self.user.timezone)
        today = now.replace(hour=7, minute=0, second=0, microsecond=0)
        friday = now + timedelta(days=(4 - now.weekday()) % 7)
        if friday.date() == now.date():
            friday = friday + timedelta(days=7)
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprise propre",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": DAY_KEYS[today.weekday()],
                    "label": day_label_fr(DAY_KEYS[today.weekday()], capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "css",
                    "session_title": "Natation CSS",
                    "session_goal": "Seuil",
                    "session_note": "",
                    "session_description": "6x100m allure CSS",
                    "duration_min": 40,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Seance cle",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": DAY_KEYS[friday.weekday()],
                    "label": day_label_fr(DAY_KEYS[friday.weekday()], capitalize=True),
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Recuperation flexible",
                    "session_goal": "Absorber",
                    "session_note": "",
                    "session_description": "Repos",
                    "duration_min": 0,
                    "intensity": "easy",
                    "load_score": 0,
                    "priority": "Recovery",
                    "nutrition_focus": "",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                },
            ],
        )
        sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=14)
        swim = next(session for session in sessions if session.sport_type == "swimming")

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.EXECUTION_UPDATE,
                confidence=0.95,
                source_text="Mince j'ai oublie piscine, swap avec vendredi",
                scope=UserIndicationScope.SINGLE_DAY,
                polarity=UserIndicationPolarity.SIGNAL,
                time_reference=IndicationTimeReference(
                    label="aujourd'hui",
                    resolved_date=today.date(),
                    day_key=DAY_KEYS[today.weekday()],
                    relative_reference="today",
                    window=None,
                ),
                execution_sport_type="swimming",
                execution_completed=False,
            )

            def fake_decide(*args, **kwargs):
                captured["timeline_summary"] = kwargs["timeline_summary"]
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Le routeur LLM doit voir la demande composee avant tout skip.",
                    fitmas_message="Je garde la demande de swap comme intention principale.",
                )

            api_messages.decide = fake_decide
            result = self.client.post(
                "/api/v0/messages",
                json={"text": "Mince j'ai complètement oublié que j'avais piscine, on peut swap la piscine de aujourd'hui avec la séance de vendredi ?"},
            ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret

        self.assertEqual(result["assistant_message"]["text"], "Je garde la demande de swap comme intention principale.")
        self.assertIn(f"id={swim.id}", str(captured.get("timeline_summary")))
        self.assertIn("status=planned", str(captured.get("timeline_summary")))
        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, swim.id)
        self.assertEqual(updated.completion_status, "planned")

    def test_llm_turn_plan_can_protect_mutation_without_keyword(self) -> None:
        now = get_local_now(self.user.timezone)
        today = now.replace(hour=7, minute=0, second=0, microsecond=0)
        friday = now + timedelta(days=(4 - now.weekday()) % 7)
        if friday.date() == now.date():
            friday = friday + timedelta(days=7)
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="reprise propre",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": DAY_KEYS[today.weekday()],
                    "label": day_label_fr(DAY_KEYS[today.weekday()], capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "css",
                    "session_title": "Natation CSS",
                    "session_goal": "Seuil",
                    "session_note": "",
                    "session_description": "6x100m allure CSS",
                    "duration_min": 40,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Seance cle",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": DAY_KEYS[friday.weekday()],
                    "label": day_label_fr(DAY_KEYS[friday.weekday()], capitalize=True),
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Recuperation flexible",
                    "session_goal": "Absorber",
                    "session_note": "",
                    "session_description": "Repos",
                    "duration_min": 0,
                    "intensity": "easy",
                    "load_score": 0,
                    "priority": "Recovery",
                    "nutrition_focus": "",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                },
            ],
        )
        sessions = repo.get_scheduled_sessions(self.db, self.user.id, limit=14)
        swim = next(session for session in sessions if session.sport_type == "swimming")

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.EXECUTION_UPDATE,
                confidence=0.95,
                source_text="Piscine impossible ce matin, vendredi a la place ?",
                scope=UserIndicationScope.SINGLE_DAY,
                polarity=UserIndicationPolarity.SIGNAL,
                time_reference=IndicationTimeReference(
                    label="aujourd'hui",
                    resolved_date=today.date(),
                    day_key=DAY_KEYS[today.weekday()],
                    relative_reference="today",
                    window=None,
                ),
                execution_sport_type="swimming",
                execution_completed=False,
            )
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="plan_mutation",
                secondary_intents=("non_completion_claim",),
                has_plan_mutation=True,
                model_dump=lambda mode="json": {
                    "primary_intent": "plan_mutation",
                    "secondary_intents": ["non_completion_claim"],
                    "has_plan_mutation": True,
                },
            )
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="Le routeur LLM protege la mutation implicite.",
                fitmas_message="Je traite vendredi a la place comme une demande de reprogrammation.",
            )

            result = self.client.post(
                "/api/v0/messages",
                json={"text": "Piscine impossible ce matin, vendredi a la place ?"},
            ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertEqual(
            result["assistant_message"]["text"],
            "Je traite vendredi a la place comme une demande de reprogrammation.",
        )
        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, swim.id)
        self.assertEqual(updated.completion_status, "planned")

    def test_targeted_execution_clarification_skipped_on_mutation_intent(self) -> None:
        """Compound: yesterday had a run, user asks to move a future session.

        The targeted execution clarification about yesterday's run must NOT
        short-circuit the pipeline when the turn plan signals a plan mutation.
        The LLM decide() must be reached.
        """
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        today = now.replace(hour=7, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        # Add a yesterday session that would trigger the clarification path.
        self.db.add(
            s.ScheduledSession(
                user_id=self.user.id,
                day=DAY_KEYS[yesterday.weekday()],
                label=day_label_fr(DAY_KEYS[yesterday.weekday()], capitalize=True),
                scheduled_date=yesterday,
                sport_type="running",
                session_type="easy",
                session_title="Footing hier",
                session_goal="Reprise",
                session_note="",
                session_description="40 min",
                duration_min=40,
                intensity="easy",
                load_score=2,
                priority="Normal",
                nutrition_focus="",
                flexibility="stable",
                completion_status="planned",
            )
        )
        self.db.commit()

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            # Ambiguous interpretation: nothing tying the message to yesterday.
            api_messages.interpret_user_indication = lambda *args, **kwargs: None
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="plan_mutation",
                secondary_intents=(),
                has_plan_mutation=True,
                model_dump=lambda mode="json": {
                    "primary_intent": "plan_mutation",
                    "secondary_intents": [],
                    "has_plan_mutation": True,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["called"] = True
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Le routeur LLM voit la demande de mutation avant toute clarification.",
                    fitmas_message="Je traite la demande de reprogrammation.",
                )

            api_messages.decide = fake_decide
            result = self.client.post(
                "/api/v0/messages",
                json={"text": "decale la seance de jeudi a vendredi"},
            ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertTrue(captured.get("called"), "decide() must be called on mutation intent")
        self.assertEqual(
            result["assistant_message"]["text"],
            "Je traite la demande de reprogrammation.",
        )
        self.assertNotIn("hier", result["assistant_message"]["text"].lower())

    def test_intent_divergence_between_heuristic_and_llm_logs_warning(self) -> None:
        """Observability: when the deterministic heuristic and the LLM turn
        planner disagree on whether the user wants a plan mutation, the
        pipeline must emit a structured WARNING so we can audit drift.

        Behavior is unchanged (OR of both signals still drives routing);
        this test exists solely to prevent regressions of the warning.
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: None
            # LLM says: NOT a plan mutation.
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="information_request",
                secondary_intents=(),
                has_plan_mutation=False,
                model_dump=lambda mode="json": {
                    "primary_intent": "information_request",
                    "secondary_intents": [],
                    "has_plan_mutation": False,
                },
            )
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="routage conservateur",
                fitmas_message="Bien recu.",
            )
            # Heuristic says: YES (message carries "deplace").
            with self.assertLogs("fitmas.conversation_pipeline", level="WARNING") as captured:
                self.client.post(
                    "/api/v0/messages",
                    json={"text": "deplace la seance de jeudi a vendredi"},
                )
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        divergence_records = [r for r in captured.records if "intent_divergence" in r.getMessage()]
        self.assertTrue(
            divergence_records,
            f"expected pipeline.intent_divergence warning, got records: {[r.getMessage() for r in captured.records]}",
        )
        message = divergence_records[0].getMessage()
        self.assertIn("heuristic=True", message)
        self.assertIn("llm=False", message)

    def test_intent_divergence_logs_llm_unavailable_when_turn_plan_missing(self) -> None:
        """Observability: when the LLM turn planner returned None (classifier
        crash, timeout, rate limit), the divergence log must distinguish
        `llm=unavailable` from `llm=False` (classifier returned a clean no).

        Both failure modes push the pipeline onto the deterministic heuristic
        alone, but they are different signals: `unavailable` is a platform
        incident to watch; `False` is a genuine disagreement worth auditing.
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: None
            # plan_conversation_turn stays set to None via setUp -> classifier unavailable.
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="routage conservateur",
                fitmas_message="Bien recu.",
            )
            # Heuristic fires (message carries "deplace").
            with self.assertLogs("fitmas.conversation_pipeline", level="WARNING") as captured:
                self.client.post(
                    "/api/v0/messages",
                    json={"text": "deplace la seance de jeudi a vendredi"},
                )
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret

        divergence_records = [r for r in captured.records if "intent_divergence" in r.getMessage()]
        self.assertTrue(divergence_records, "expected pipeline.intent_divergence warning")
        message = divergence_records[0].getMessage()
        self.assertIn("heuristic=True", message)
        self.assertIn("llm=unavailable", message)

    def test_calibration_standalone_ack_skipped_on_compound_mutation(self) -> None:
        """Open calibration + compound mutation in same message.

        With an open availability calibration need, a message that both answers
        the calibration AND asks for a mutation must NOT short-circuit to the
        calibration ack. The LLM decide() must arbitrate.
        """
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        need = calibration_needs.CalibrationNeed(
            id="availability_window:availability:thursday",
            need_type=calibration_needs.CalibrationNeedType.AVAILABILITY_WINDOW,
            topic="availability:thursday",
            status=calibration_needs.CalibrationNeedStatus.OPEN,
            why_now="test",
            priority=calibration_needs.CalibrationNeedPriority.MEDIUM,
            source="heartbeat_morning",
            channel_hint="telegram",
            created_at=now.isoformat(timespec="minutes"),
            expires_at=(now + timedelta(days=3)).isoformat(timespec="minutes"),
            last_prompted_at=now.isoformat(timespec="minutes"),
            context={"day": "thursday", "day_label": "jeudi", "session_id": 12, "session_title": "Tempo"},
            allowed_answers=("morning", "evening", "both", "none"),
            write_targets=("working_memory.availability",),
        )
        repo.upsert_working_memory(self.db, self.user.id, [need.as_memory_update()])

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: None
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="plan_mutation",
                secondary_intents=("calibration_answer",),
                has_plan_mutation=True,
                model_dump=lambda mode="json": {
                    "primary_intent": "plan_mutation",
                    "secondary_intents": ["calibration_answer"],
                    "has_plan_mutation": True,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["called"] = True
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Compound: calibration + mutation, LLM arbitre.",
                    fitmas_message="Je note le creneau et je traite la demande de swap.",
                )

            api_messages.decide = fake_decide
            # "plutot le soir, swap piscine" — 5 tokens, passes is_standalone_calibration_answer
            result = self.client.post(
                "/api/v0/messages",
                json={"text": "plutot le soir, swap piscine"},
            ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertTrue(
            captured.get("called"),
            "decide() must be called when calibration answer is compounded with a mutation",
        )
        self.assertEqual(
            result["assistant_message"]["text"],
            "Je note le creneau et je traite la demande de swap.",
        )

    def test_low_signal_label_refuses_rich_signal(self) -> None:
        """The low-signal classifier is defense-in-depth: if any rich signal
        marker appears in the message, it must refuse to label as low-signal
        so decide() arbitrates the response (Chantier 1 autonomy refactor:
        the classifier no longer short-circuits the LLM).
        """
        # Baseline: pure ack is labelled "ack".
        self.assertEqual(
            api_messages._maybe_low_signal_label("merci", has_open_calibration_need=False),
            "ack",
        )
        # Defense-in-depth: simulate a hypothetical compound where normalize
        # happens to equal an ACK phrase AND contains a rich marker.
        original_ack_texts = api_messages._ACK_TEXTS
        try:
            api_messages._ACK_TEXTS = original_ack_texts | {"merci decale"}
            self.assertIsNone(
                api_messages._maybe_low_signal_label(
                    "merci decale",
                    has_open_calibration_need=False,
                ),
                "Classifier must refuse when a rich mutation marker is present",
            )
        finally:
            api_messages._ACK_TEXTS = original_ack_texts

    def test_future_constraint_without_candidate_routes_context_to_llm(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, str] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="availability_constraint",
                secondary_intents=(),
                has_plan_mutation=False,
                model_dump=lambda mode="json": {
                    "primary_intent": "availability_constraint",
                    "secondary_intents": [],
                    "has_plan_mutation": False,
                },
            )

            def fake_decide(*args, **kwargs):
                captured["signal_summary"] = kwargs.get("signal_summary") or ""
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Aucune seance candidate dans cette fenetre.",
                    fitmas_message="Rien a bouger demain soir.",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "Je ne suis pas dispo demain soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertIn("Rien a bouger", result["assistant_message"]["text"])
        self.assertIn("Rien a bouger", captured["signal_summary"])

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
        captured: dict[str, str] = {}
        try:
            # Chantier 1 (autonomy refactor): the execution contestation
            # grounding is now passed to decide() as prompt context. We assert
            # decide() runs and receives the contestation context, and we stub
            # it to produce the canonical wording so we can still verify the
            # downgrade side effect (handled before the LLM call).
            def fake_decide(*args, **kwargs):
                captured["activity_claim_summary"] = kwargs.get("activity_claim_summary") or ""
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Contestation execution sans mutation a appliquer.",
                    fitmas_message="Bien note. Je ne compte pas cette sortie comme faite.",
                )

            api_messages.decide = fake_decide
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
        self.assertIn("contestation", captured["activity_claim_summary"].lower())
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
        now = get_local_now(self.user.timezone)
        need = calibration_needs.CalibrationNeed(
            id="availability_window:availability:thursday",
            need_type=calibration_needs.CalibrationNeedType.AVAILABILITY_WINDOW,
            topic="availability:thursday",
            status=calibration_needs.CalibrationNeedStatus.OPEN,
            why_now="test",
            priority=calibration_needs.CalibrationNeedPriority.MEDIUM,
            source="heartbeat_morning",
            channel_hint="telegram",
            created_at=now.isoformat(timespec="minutes"),
            expires_at=(now + timedelta(days=3)).isoformat(timespec="minutes"),
            last_prompted_at=now.isoformat(timespec="minutes"),
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

    def test_standalone_calibration_answer_wins_over_availability_parse(self) -> None:
        _, session = self._create_plan_with_tomorrow_session()
        now = get_local_now(self.user.timezone)
        target_date = session.scheduled_date.date()
        need = calibration_needs.CalibrationNeed(
            id="availability_window:availability:thursday",
            need_type=calibration_needs.CalibrationNeedType.AVAILABILITY_WINDOW,
            topic="availability:thursday",
            status=calibration_needs.CalibrationNeedStatus.OPEN,
            why_now="test",
            priority=calibration_needs.CalibrationNeedPriority.MEDIUM,
            source="heartbeat_morning",
            channel_hint="telegram",
            created_at=now.isoformat(timespec="minutes"),
            expires_at=(now + timedelta(days=3)).isoformat(timespec="minutes"),
            last_prompted_at=now.isoformat(timespec="minutes"),
            context={
                "day": DAY_KEYS[target_date.weekday()],
                "day_label": day_label_fr(DAY_KEYS[target_date.weekday()]),
                "session_id": session.id,
                "session_title": session.session_title,
            },
            allowed_answers=("morning", "evening", "both", "none"),
            write_targets=("working_memory.availability",),
        )
        repo.upsert_working_memory(self.db, self.user.id, [need.as_memory_update()])
        expected_day_label = day_label_fr(DAY_KEYS[target_date.weekday()])

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_calibration_extract = conversation_pipeline.extract_calibration_resolution
        original_calibration_ack = conversation_pipeline.generate_calibration_ack
        try:
            def should_not_run(*args, **kwargs):
                raise AssertionError("LLM decide should not run for standalone calibration answers")

            api_messages.decide = should_not_run
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
                confidence=0.9,
                source_text="Plutot le soir",
                scope=UserIndicationScope.SINGLE_DAY,
                polarity=UserIndicationPolarity.UNAVAILABLE,
                time_reference=IndicationTimeReference(
                    label="soir",
                    resolved_date=target_date,
                    day_key=DAY_KEYS[target_date.weekday()],
                    relative_reference="tomorrow",
                    window="evening",
                ),
            )
            conversation_pipeline.extract_calibration_resolution = lambda *args, **kwargs: calibration_needs.CalibrationResolution(
                need_id=need.id,
                resolved=True,
                normalized_value={
                    "day": DAY_KEYS[target_date.weekday()],
                    "windows": ["evening"],
                    "hard_blocked": ["morning"],
                },
                confidence=0.93,
                followup_needed=False,
                raw_summary="Plutot le soir",
            )
            conversation_pipeline.generate_calibration_ack = (
                lambda **kwargs: f"OK, je note {expected_day_label}: plutot le soir."
            )
            result = self.client.post("/api/v0/messages", json={"text": "Plutot le soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            conversation_pipeline.extract_calibration_resolution = original_calibration_extract
            conversation_pipeline.generate_calibration_ack = original_calibration_ack

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        # The ack must name the day of the target session (tomorrow relative
        # to today's test run), not a hard-coded weekday.
        self.assertIn(expected_day_label, result["assistant_message"]["text"].lower())
        self.assertEqual(updated.completion_status, "planned")

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

    def test_availability_constraint_persists_as_fact_with_window_anchored_expires_at(self) -> None:
        """Chantier 4: a multi-day AVAILABILITY_CONSTRAINT surfaced by
        interpret_user_indication must be persisted as a UserFact with
        category=availability, a key encoding start/end dates, and
        expires_at anchored on window_end + 1 day so it stays active for
        the whole constraint and is auto-filtered out afterwards."""
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        start = now.date() + timedelta(days=1)
        end = start + timedelta(days=13)  # 14-day window inclusive

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_interpret = api_messages.interpret_user_indication
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.interpret_user_indication = lambda *args, **kwargs: UserIndication(
                kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
                confidence=0.9,
                source_text="je n'ai pas acces a la piscine pendant 2 semaines",
                scope=UserIndicationScope.WEEK,
                polarity=UserIndicationPolarity.UNAVAILABLE,
                time_reference=IndicationTimeReference(
                    label="window",
                    resolved_date=start,
                    day_key=None,
                    relative_reference=None,
                    window=None,
                    window_end_date=end,
                ),
            )
            api_messages.plan_conversation_turn = lambda *args, **kwargs: None
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="note prise",
                fitmas_message="Bien note.",
            )
            self.client.post(
                "/api/v0/messages",
                json={"text": "je n'ai pas acces a la piscine pendant 2 semaines"},
            )
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.interpret_user_indication = original_interpret
            api_messages.plan_conversation_turn = original_plan_turn

        facts = (
            self.db.query(s.UserFact)
            .filter(s.UserFact.user_id == self.user.id, s.UserFact.category == "availability")
            .all()
        )
        self.assertEqual(len(facts), 1, f"expected 1 availability fact, got {[(f.category, f.key) for f in facts]}")
        fact = facts[0]
        self.assertEqual(
            fact.key,
            f"unavailable_swimming_{start.isoformat()}_{end.isoformat()}",
        )
        self.assertTrue(fact.active)
        # expires_at = end + 1 day at midnight (stays active through the last day).
        self.assertEqual(
            fact.expires_at,
            datetime.combine(end + timedelta(days=1), datetime.min.time()),
        )

    def test_execution_clarification_skipped_when_active_availability_fact_covers_yesterday(self) -> None:
        """Chantier 4: yesterday had a swimming session and an active availability
        fact covering that date exists (key = unavailable_swimming_<yesterday>_<later>).
        The targeted execution clarification must NOT re-ask "tu l'as faite ou pas ?"
        — the coach already knows the pool is closed."""
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        today = now.replace(hour=7, minute=0, second=0, microsecond=0)
        yesterday_dt = today - timedelta(days=1)
        yesterday_date = yesterday_dt.date()
        self.db.add(
            s.ScheduledSession(
                user_id=self.user.id,
                day=DAY_KEYS[yesterday_dt.weekday()],
                label=day_label_fr(DAY_KEYS[yesterday_dt.weekday()], capitalize=True),
                scheduled_date=yesterday_dt,
                sport_type="swimming",
                session_type="endurance",
                session_title="Natation technique",
                session_goal="Maintien",
                session_note="",
                session_description="45 min",
                duration_min=45,
                intensity="easy",
                load_score=2,
                priority="Normal",
                nutrition_focus="",
                flexibility="stable",
                completion_status="planned",
            )
        )
        # Active availability fact: pool closed yesterday → + 13 days.
        end_date = yesterday_date + timedelta(days=13)
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="availability",
                key=f"unavailable_swimming_{yesterday_date.isoformat()}_{end_date.isoformat()}",
                value="Indisponibilite declaree : piscine fermee pendant 2 semaines",
                source="conversation",
                confidence=0.9,
                confirmed=False,
                active=True,
                urgency="medium",
                ttl="short",
                affects_json="[]",
                expires_at=datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
            )
        )
        self.db.commit()

        from fitmas.conversation_context import build_conversation_context

        scheduled_payloads = [
            {
                "id": row.id,
                "day": row.day,
                "scheduled_date": row.scheduled_date,
                "sport_type": row.sport_type,
                "session_title": row.session_title,
                "completion_status": row.completion_status,
            }
            for row in repo.get_scheduled_sessions_between_dates(
                self.db,
                self.user.id,
                start_date=today.date() - timedelta(days=13),
                end_date=today.date() + timedelta(days=7),
                limit=42,
            )
        ]
        context = build_conversation_context(
            user_text="rien de special",
            conversation_history=[],
            timezone_name=self.user.timezone,
            scheduled_sessions=scheduled_payloads,
            activities=[],
            active_facts=[],
            now=today,
        )

        clarification = api_messages._targeted_execution_clarification(
            db=self.db,
            user=self.user,
            conversation_context=context,
            user_indication=None,
            resolved_non_completion_claim=None,
            resolved_activity_claim=None,
            previous_agent_text=None,
        )
        self.assertIsNone(
            clarification,
            "Availability fact covering yesterday must suppress the execution clarification",
        )

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
