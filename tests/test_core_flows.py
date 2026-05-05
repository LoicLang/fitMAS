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
import fitmas.plan_mutation_service as plan_mutation_service
from fitmas.adaptation import AdaptationResult
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import CoachDecision, MutationDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchOperationValidation, PlanPatchValidation
from fitmas.plan_actions import move_session
from fitmas.training_load import compute_ctl_atl_tsb, estimate_tss
from fitmas import repository as repo, schema as s
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now
from fitmas.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


def _valid_week_review(*args, **kwargs) -> WeekCoherenceReview:
    return WeekCoherenceReview(
        status="valid",
        sport_quality="good",
        confidence=0.86,
        summary="review semaine valide",
        findings=(
            WeekCoherenceFinding(
                code="mission_preserved",
                severity="info",
                detail="Review test.",
            ),
        ),
        suggested_adjustments=(),
        recommended_policy="commit_original",
    )


def _confirm_week_review(*args, **kwargs) -> WeekCoherenceReview:
    return WeekCoherenceReview(
        status="requires_confirmation",
        sport_quality="fragile",
        confidence=0.86,
        summary="La semaine devient fragile.",
        findings=(
            WeekCoherenceFinding(
                code="mission_diluted",
                severity="requires_confirmation",
                detail="Le patch degrade la coherence semaine.",
            ),
        ),
        suggested_adjustments=(),
        recommended_policy="confirm_original",
    )


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
        self._original_week_review = plan_mutation_service.review_week_coherence_with_llm
        plan_mutation_service.review_week_coherence_with_llm = _valid_week_review

    def tearDown(self) -> None:
        api_messages.plan_conversation_turn = self._original_plan_conversation_turn
        plan_mutation_service.review_week_coherence_with_llm = self._original_week_review
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
        source_date = session.scheduled_date.date()
        moved = move_session(
            self.db,
            user=self.user,
            session_id=session.id,
            target_date=source_date + timedelta(days=8),
        )
        self.assertIsNotNone(moved)
        sessions = [repo.to_pydantic_scheduled_session(x) for x in repo.get_scheduled_sessions(self.db, self.user.id, limit=10)]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].sport_type, "rest")
        self.assertEqual(sessions[0].completion_status, "adapted")
        self.assertEqual(sessions[1].session_title, "Footing facile")
        self.assertEqual(sessions[1].id, session.id)
        self.assertEqual(sessions[1].scheduled_date, (source_date + timedelta(days=8)).isoformat())

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

    def test_high_impact_confirmation_yes_does_not_auto_apply_without_llm_resolution(self) -> None:
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
        self.assertEqual(refreshed_session.sport_type, "running")
        self.assertIn("confirmes", second["assistant_message"]["text"].lower())
        self.assertIsNotNone(pending)

    def test_legacy_mutation_decision_runs_week_gate_before_commit(self) -> None:
        now = get_local_now(self.user.timezone)
        scheduled_at = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        target_date = (now + timedelta(days=3)).date().isoformat()
        session = s.ScheduledSession(
            user_id=self.user.id,
            day=DAY_KEYS[scheduled_at.weekday()],
            label=day_label_fr(DAY_KEYS[scheduled_at.weekday()], capitalize=True),
            scheduled_date=scheduled_at,
            sport_type="cycling",
            session_type="easy",
            session_title="Velo souple",
            session_goal="Support",
            duration_min=45,
            intensity="easy",
            load_score=1,
            priority="Normal",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_week_review = plan_mutation_service.review_week_coherence_with_llm
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="move_session",
                target_session_id=session.id,
                target_date=target_date,
                rationale="Deplacement low-risk demande par le user.",
                fitmas_message="Je deplace le velo souple.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            plan_mutation_service.review_week_coherence_with_llm = _confirm_week_review
            result = self.client.post("/api/v0/messages", json={"text": "Deplace le velo souple a dimanche"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            plan_mutation_service.review_week_coherence_with_llm = original_week_review

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)
        events = self.db.query(s.PlanMutationEventRecord).filter(s.PlanMutationEventRecord.user_id == self.user.id).all()

        self.assertIsNotNone(refreshed_session)
        self.assertEqual(refreshed_session.scheduled_date.date(), scheduled_at.date())
        self.assertEqual(events, [])
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "plan_patch")
        self.assertIn("fragile", pending.summary.lower())
        self.assertIn("confirm", result["assistant_message"]["text"].lower())

    def test_plan_patch_pending_yes_does_not_auto_apply_without_llm_resolution(self) -> None:
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
        self.assertEqual(refreshed_session.session_title, "Footing facile")
        self.assertNotEqual(refreshed_session.intensity, "hard")
        self.assertIn("confirmes", second["assistant_message"]["text"].lower())
        self.assertIsNotNone(active_pending)
        self.assertEqual(events, [])

    def test_plan_patch_pending_accept_resolution_applies_pending_patch(self) -> None:
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
            def fake_decide(user_text, *args, **kwargs):
                if str(user_text).strip().lower() == "oui":
                    return CoachDecision(
                        response_type="no_change",
                        rationale="acceptation pending comprise par le LLM",
                        fitmas_message="C'est confirme. Je l'applique.",
                        pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
                    )
                return CoachDecision(
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

            api_messages.decide = fake_decide
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
        all_pending = self.db.query(s.PendingMutationConfirmation).order_by(s.PendingMutationConfirmation.id).all()
        events = (
            self.db.query(s.PlanMutationEventRecord)
            .filter(s.PlanMutationEventRecord.user_id == self.user.id)
            .order_by(s.PlanMutationEventRecord.id.desc())
            .all()
        )

        self.assertIn("Tu confirmes", first["assistant_message"]["text"])
        self.assertIsNotNone(pending)
        self.assertIn("tempo dur", second["assistant_message"]["text"].lower())
        self.assertEqual(refreshed_session.session_title, "Tempo dur")
        self.assertEqual(refreshed_session.intensity, "hard")
        self.assertIsNone(active_pending)
        self.assertEqual(all_pending[0].status, "accepted")
        self.assertEqual(events[0].command_type, "replace_session")

    def test_high_impact_confirmation_no_keeps_plan_unchanged(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(user_text, *args, **kwargs):
                if str(user_text).strip().lower() == "non":
                    return MutationDecision(
                        mutation_type="no_change",
                        rationale="Refus du pending compris par le LLM.",
                        fitmas_message="Je ne touche pas au planning.",
                    )
                return MutationDecision(
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

            api_messages.decide = fake_decide
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

    def test_message_client_key_returns_existing_turn_without_reprocessing(self) -> None:
        repo.add_conversation_turn(
            self.db,
            user_id=self.user.id,
            user_message="Remplace les natations",
            assistant_message="C'est deja traite.",
            response_mode="plan_patch_applied",
            extraction_confidence=0.85,
            day_updated=None,
            mutation_type="",
            mutation_applied=True,
            pending_confirmation=False,
            pending_confirmation_id=None,
            decision_json="{}",
            context={"client_message_key": "telegram:42:1003", "source": "telegram"},
            memory_writes=[],
        )
        original_decide = api_messages.decide
        try:
            def fail_decide(*args, **kwargs):
                raise AssertionError("Duplicate client key should not re-enter LLM decision")

            api_messages.decide = fail_decide
            result = self.client.post(
                "/api/v0/messages",
                json={
                    "text": "Remplace les natations",
                    "client_message_key": "telegram:42:1003",
                    "source": "telegram",
                },
            ).json()
        finally:
            api_messages.decide = original_decide

        self.assertEqual(result["assistant_message"]["text"], "C'est deja traite.")
        self.assertEqual(result["user_message"]["text"], "Remplace les natations")

    def test_pending_reject_resolution_closes_pending_without_mutation(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(user_text, *args, **kwargs):
                if str(user_text).strip().lower() == "non":
                    return CoachDecision(
                        response_type="no_change",
                        rationale="refus pending compris par le LLM",
                        fitmas_message="OK. Je ne touche pas au planning.",
                        pending_resolution=llm.RejectPendingResolution(type="reject_pending"),
                    )
                return MutationDecision(
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

            api_messages.decide = fake_decide
            api_messages.extract_facts = lambda *args, **kwargs: []
            self.client.post("/api/v0/messages", json={"text": "Tu peux remplacer ma seance ?"})
            self.client.post("/api/v0/messages", json={"text": "non"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed_session = repo.get_scheduled_session(self.db, self.user.id, session.id)
        active_pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)
        all_pending = self.db.query(s.PendingMutationConfirmation).order_by(s.PendingMutationConfirmation.id).all()

        self.assertEqual(refreshed_session.sport_type, "running")
        self.assertIsNone(active_pending)
        self.assertEqual(all_pending[0].status, "rejected")

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
        original_apply = conversation_pipeline.apply_patch_for_user
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="move_session",
                target_session_id=session.id,
                target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                rationale="unsafe move",
                fitmas_message="OK. Je deplace la seance demain.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            conversation_pipeline.apply_patch_for_user = lambda *args, **kwargs: plan_mutation_service.PlanPatchServiceResult(
                validation=PlanPatchValidation(
                    status="blocked",
                    operation_results=(
                        PlanPatchOperationValidation(
                            operation_type="move_session",
                            status="blocked",
                            target_session_id=session.id,
                            block_reason="protected_recovery_target",
                        ),
                    ),
                ),
                week_policy_status="blocked",
            )
            result = self.client.post("/api/v0/messages", json={"text": "Mets ca demain"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            conversation_pipeline.apply_patch_for_user = original_apply

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

    def test_coach_decision_requires_confirmation_plan_patch_creates_pending(self) -> None:
        _, session = self._create_plan_for_today()
        original_date = session.scheduled_date.date()
        target_date = (original_date + timedelta(days=2)).isoformat()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="requires_confirmation",
                rationale="deplacement sensible demande par le coach",
                fitmas_message="Je peux le faire, mais je veux ton feu vert avant de toucher la semaine.",
                confirmation_reason="deplacement sensible",
                plan_patch=PlanPatch(
                    coach_message="Je peux deplacer la seance.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=target_date,
                            rationale="Indisponibilite annoncee.",
                        )
                    ],
                ),
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "Je ne suis pas dispo"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        pending = repo.get_active_pending_mutation_confirmation(self.db, self.user.id)
        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.scheduled_date.date(), original_date)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "plan_patch")
        self.assertEqual(turns[0].response_mode, "plan_patch_confirmation")
        self.assertTrue(turns[0].pending_confirmation)
        self.assertIn("confirm", result["assistant_message"]["text"].lower())

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

    def test_message_flow_does_not_replan_simple_unavailability_without_llm(self) -> None:
        _, session = self._create_plan_for_today()
        next_day_key = DAY_KEYS[(session.scheduled_date.date().weekday() + 1) % 7]
        self.user.weekly_structure_notes = f"{day_label_fr(next_day_key, capitalize=True)} matin dispo."
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
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

        self.assertIn("Reessaie", result["assistant_message"]["text"])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(planned_sessions), 1)
        self.assertEqual(planned_sessions[0].scheduled_date.date(), session.scheduled_date.date())
        self.assertIsNone(latest_adaptation)
        self.assertIsNone(overview["last_adaptation"])
        self.assertFalse(any(item["status"] == "adapted" for item in calendar["feed"]))

    def test_message_flow_does_not_handle_fatigue_without_llm(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
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
        self.assertEqual(adapted_session.completion_status, "planned")
        events = self.db.query(s.PlanMutationEventRecord).all()
        self.assertEqual(events, [])

    def test_message_flow_surfaces_targeted_clarification_as_prompt_context_to_llm(self) -> None:
        """Chantier 3bis (autonomy refactor): the targeted execution
        clarification no longer short-circuits the pipeline with a canned
        "Tu l'as faite ou pas ?" reply (which looped on missed sessions).
        It is surfaced as soft prompt context — the LLM arbitrates whether
        to ask, integrate or move on."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        captured: dict[str, object] = {}
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            def fake_decide(*args, **kwargs):
                coach_context = kwargs.get("coach_context", {})
                captured["unresolved_followup"] = coach_context.get("unresolved_execution_followup")
                captured["unresolved_followup_session_id"] = coach_context.get("unresolved_execution_followup_session_id")
                captured["unresolved_followup_target_date"] = coach_context.get("unresolved_execution_followup_target_date")
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
        self.assertEqual(captured.get("unresolved_followup_session_id"), yesterday_session.id)
        self.assertTrue(str(captured.get("unresolved_followup_target_date") or "").strip())

    def test_targeted_clarification_does_not_trigger_fatigue_adaptation_without_llm(self) -> None:
        """Phase 0: fatigue text is not auto-adapted when the LLM decision is unavailable."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        today_session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(today_session)
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: None
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
        self.assertEqual(refreshed_today.completion_status, "planned")
        self.assertIsNone(latest_adaptation)

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

    def test_contextual_non_answer_stays_llm_only_without_parser_side_effect(self) -> None:
        """Phase 0 LLM-first: a short "Non" after a clarification is handled
        by the LLM reply path, not by a deterministic non-completion parser
        that mutates the session behind the coach's back."""
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

        self.assertIn("Je ne compte pas", second["assistant_message"]["text"])
        self.assertEqual(refreshed_yesterday.completion_status, "planned")

    def test_health_reply_after_clarification_is_ingested_normally(self) -> None:
        """Chantier 3bis: an illness reply on the second turn must still
        route through the health adaptation flow without the canned
        clarification reasserting itself."""
        _, yesterday_session = self._seed_uncertain_yesterday_key_session()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        try:
            def fake_decide(user_text, *args, **kwargs):
                if "malade" in user_text:
                    return CoachDecision(
                        response_type="no_change",
                        rationale="Maladie signalee, le coach arbitre sans fallback deterministe.",
                        fitmas_message="Tu es malade, donc on ne force rien aujourd'hui.",
                        memory_actions=[
                            llm.HealthSignalAction(
                                type="record_health_signal",
                                health_signal="maladie",
                                body_area="general",
                                severity="unknown",
                                status="new",
                                confidence=0.95,
                                evidence="Je suis malade",
                            )
                        ],
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
            self.client.post("/api/v0/messages", json={"text": "Tu me conseilles quoi aujourd'hui ?"}).json()
            second = self.client.post("/api/v0/messages", json={"text": "Je suis malade comme un chien j'ai rien fait"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.check_and_adapt_health_facts = original_health

        self.db.expire_all()
        refreshed_yesterday = repo.get_scheduled_session(self.db, self.user.id, yesterday_session.id)
        facts = self.client.get("/api/v0/facts").json()

        self.assertIn("malade", second["assistant_message"]["text"].lower())
        self.assertEqual(refreshed_yesterday.completion_status, "planned")
        self.assertTrue(any(fact["category"] == "health" for fact in facts))

    def test_message_flow_does_not_replan_future_availability_constraint_without_llm(self) -> None:
        _, tomorrow_session = self._create_plan_with_tomorrow_session()
        original_date = tomorrow_session.scheduled_date.date()
        next_open_key = DAY_KEYS[(tomorrow_session.scheduled_date.date().weekday() + 2) % 7]
        self.user.weekly_structure_notes = f"{day_label_fr(next_open_key, capitalize=True)} soir dispo."
        self.db.commit()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
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

        self.assertIn("Reessaie", result["assistant_message"]["text"])
        self.assertEqual(moved_tomorrow_session.scheduled_date.date(), original_date)

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
        self.assertNotIn("Adaptation candidate", captured["temporal_summary"])

    def test_health_indication_reaches_decide_before_protective_fallback(self) -> None:
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        decide_calls = {"count": 0}
        try:
            def fake_decide(*args, **kwargs):
                decide_calls["count"] += 1
                return CoachDecision(
                    response_type="no_change",
                    rationale="Signal sante arbitre par le coach.",
                    fitmas_message="Je prends l'epaule au serieux avant de toucher au plan.",
                    memory_actions=[
                        llm.HealthSignalAction(
                            type="record_health_signal",
                            health_signal="douleur epaule quand il nage",
                            body_area="epaule",
                            severity="unknown",
                            status="new",
                            evidence="J'ai mal a l'epaule quand je nage",
                        )
                    ],
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

    def test_health_adaptation_suggestion_is_not_used_when_llm_unavailable(self) -> None:
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
        self.assertIsNone(pending)
        self.assertIn("Reessaie", result["assistant_message"]["text"])

    def test_compound_health_and_plan_mutation_reaches_llm_before_health_adaptation(self) -> None:
        _, session = self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_health = api_messages.check_and_adapt_health_facts
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []

            def should_not_run_health(*args, **kwargs):
                raise AssertionError("health adaptation should not run before LLM on compound mutation turns")

            api_messages.check_and_adapt_health_facts = should_not_run_health
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
                return CoachDecision(
                    response_type="no_change",
                    rationale="Signal sante + demande de mutation a arbitrer ensemble.",
                    fitmas_message="Je tiens compte de l'epaule avant de bouger la piscine.",
                    memory_actions=[
                        llm.HealthSignalAction(
                            type="record_health_signal",
                            health_signal="douleur epaule en nageant",
                            body_area="epaule",
                            severity="unknown",
                            status="new",
                            confidence=0.95,
                            evidence="J'ai mal a l'epaule quand je nage",
                        )
                    ],
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
            api_messages.plan_conversation_turn = original_plan_turn

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        facts = self.client.get("/api/v0/facts").json()
        self.assertEqual(result["assistant_message"]["text"], "Je tiens compte de l'epaule avant de bouger la piscine.")
        self.assertEqual(updated.completion_status, "planned")
        self.assertTrue(any(fact["category"] == "health" for fact in facts))

    def test_health_indication_is_not_reprocessed_by_post_reply_adapter(self) -> None:
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

        self.assertEqual(call_count["health"], 0)

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
        self.assertIn("reference principale: unspecified", captured["temporal_summary"])
        self.assertEqual(captured["activity_claim_summary"], "")
        self.assertIn("big_session_done", captured["signal_summary"])
        self.assertNotIn("Activite declaree par l'utilisateur", captured["selected_facts"])

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

    def test_short_ack_goes_to_llm_without_low_signal_context(self) -> None:
        """Phase 0 LLM-first: even a short ack is not classified by a
        deterministic low-signal helper. The LLM receives the raw turn and
        decides the answer itself.
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
        self.assertNotIn("low-signal", captured["temporal_summary"])

    def test_claim_without_mutation_is_repaired_via_llm(self) -> None:
        """Chantier 1bis - 3 mai 2026 : si le LLM affirme une action
        ("Je libere ce creneau") sans qu'aucune mutation ne soit committee
        ce tour, le pipeline doit tenter un LLM repair pour reecrire en voix
        coach SANS claim. C'est le path doctrine-correct (plus de canned
        template "Je n'ai applique aucun changement...").
        """
        self._create_plan_for_today()
        original_decide = api_messages.decide
        from fitmas import conversation_pipeline as cpipeline

        original_request_text = cpipeline.gw.request_text
        captured_repair: dict[str, str] = {}
        try:
            def fake_decide(*args, **kwargs):
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Phantom action emise par le LLM.",
                    fitmas_message="OK. Je libere ce creneau et je garde la suite propre.",
                )

            def fake_repair(*, system, prompt, **_kwargs):
                captured_repair["system"] = system
                captured_repair["prompt"] = prompt
                return "Mercredi note. Tu veux qu'on bouge la seance ou que tu garde le creneau libre ?"

            api_messages.decide = fake_decide
            cpipeline.gw.request_text = fake_repair
            result = self.client.post(
                "/api/v0/messages", json={"text": "Mercredi"}
            ).json()
        finally:
            api_messages.decide = original_decide
            cpipeline.gw.request_text = original_request_text

        text = result["assistant_message"]["text"]
        # Le claim 1ere personne est retire
        self.assertNotIn("Je libere", text)
        # Le repair LLM a ete appele avec le contexte attendu
        self.assertIn("Je libere ce creneau", captured_repair["prompt"])
        self.assertIn("Mercredi", captured_repair["prompt"])
        # Plus aucune trace de la vieille canned template doctrine-violante
        self.assertNotIn("n'ai applique aucun changement", text)
        # Le texte vient bien du repair LLM (pas du fallback outage)
        self.assertIn("Mercredi note", text)

    def test_claim_without_mutation_falls_back_when_repair_fails(self) -> None:
        """Chantier 1bis - 3 mai 2026 : si le LLM repair echoue (down ou
        invalide), le pipeline retombe sur `outage_fallback_reply()` --
        ligne minimale coach-voice, JAMAIS la vieille canned template.
        """
        from fitmas.claim_guard import outage_fallback_reply
        from fitmas import conversation_pipeline as cpipeline

        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_request_text = cpipeline.gw.request_text
        try:
            def fake_decide(*args, **kwargs):
                return MutationDecision(
                    mutation_type="no_change",
                    rationale="Phantom action emise par le LLM.",
                    fitmas_message="OK. Je libere ce creneau.",
                )

            def fake_repair_down(*, system, prompt, **_kwargs):
                return None  # simulate LLM outage

            api_messages.decide = fake_decide
            cpipeline.gw.request_text = fake_repair_down
            result = self.client.post(
                "/api/v0/messages", json={"text": "Mercredi"}
            ).json()
        finally:
            api_messages.decide = original_decide
            cpipeline.gw.request_text = original_request_text

        text = result["assistant_message"]["text"]
        self.assertNotIn("Je libere", text)
        self.assertEqual(text, outage_fallback_reply())
        # La vieille canned ne doit plus apparaitre dans aucun chemin.
        self.assertNotIn("n'ai applique aucun changement", text)

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
                    rationale="Contrainte large, besoin confirmation.",
                    fitmas_message="Je vois les seances touchees. Tu confirmes off complet ?",
                )

            api_messages.decide = fake_decide
            result = self.client.post("/api/v0/messages", json={"text": "Cette semaine je voyage de mercredi a vendredi"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertEqual(result["assistant_message"]["text"], "Je vois les seances touchees. Tu confirmes off complet ?")
        self.assertNotIn("Natation hotel", captured["signal_summary"])
        self.assertNotIn("Renfo hotel", captured["signal_summary"])
        self.assertNotIn("this_week", captured["signal_summary"])

    def test_swap_wording_reaches_llm_without_availability_shortcut(self) -> None:
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
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []

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
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []

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
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
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
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
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
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertTrue(captured.get("called"), "decide() must be called on mutation intent")
        self.assertEqual(
            result["assistant_message"]["text"],
            "Je traite la demande de reprogrammation.",
        )
        self.assertNotIn("hier", result["assistant_message"]["text"].lower())

    def test_removed_intent_heuristic_does_not_log_divergence_with_llm(self) -> None:
        """Phase 0: no deterministic mutation heuristic runs beside the LLM."""
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
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
            with self.assertNoLogs("fitmas.conversation_pipeline", level="WARNING"):
                self.client.post("/api/v0/messages", json={"text": "deplace la seance de jeudi a vendredi"})
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

    def test_turn_plan_missing_does_not_fall_back_to_intent_heuristic(self) -> None:
        """Phase 0: classifier outage no longer activates a regex mutation heuristic."""
        self._create_plan_for_today()
        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="routage conservateur",
                fitmas_message="Bien recu.",
            )
            with self.assertNoLogs("fitmas.conversation_pipeline", level="WARNING"):
                result = self.client.post(
                    "/api/v0/messages",
                    json={"text": "deplace la seance de jeudi a vendredi"},
                ).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.assertEqual(result["assistant_message"]["text"], "Bien recu.")

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
        original_plan_turn = api_messages.plan_conversation_turn
        captured: dict[str, object] = {}
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
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
            api_messages.plan_conversation_turn = original_plan_turn

        self.assertTrue(
            captured.get("called"),
            "decide() must be called when calibration answer is compounded with a mutation",
        )
        self.assertEqual(
            result["assistant_message"]["text"],
            "Je note le creneau et je traite la demande de swap.",
        )

    def test_low_signal_classifier_removed_from_runtime(self) -> None:
        self.assertFalse(hasattr(api_messages, "_maybe_low_signal_label"))

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
        self.assertNotIn("Rien a bouger", captured["signal_summary"])

    def test_message_flow_does_not_persist_unlogged_activity_claim_fact_without_llm_action(self) -> None:
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

        self.assertEqual(facts, [])

    def test_message_flow_does_not_archive_superseded_claim_after_temporal_correction_without_llm_action(self) -> None:
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

        self.assertEqual(facts, [])

    def test_explicit_non_completion_correction_stays_llm_only_without_side_effect(self) -> None:
        _, session = self._create_plan_for_today()
        session.scheduled_date = session.scheduled_date - timedelta(days=1)
        session.day = DAY_KEYS[session.scheduled_date.weekday()]
        session.completion_status = "done"
        self.db.commit()

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        captured: dict[str, str] = {}
        try:
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
        self.assertEqual(captured["activity_claim_summary"], "")
        self.assertEqual(updated.completion_status, "done")

    def test_coach_decision_execution_action_marks_session_skipped(self) -> None:
        _, session = self._create_plan_for_today()
        session.scheduled_date = session.scheduled_date - timedelta(days=1)
        session.day = DAY_KEYS[session.scheduled_date.weekday()]
        session.sport_type = "strength"
        session.session_title = "Renfo 34min"
        self.db.commit()
        self.db.refresh(session)

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="no_change",
                rationale="execution manquee comprise par le LLM",
                fitmas_message="Note pour hier. On garde ce matin simple et on avance.",
                execution_actions=[
                    llm.ExecutionUpdateAction(
                        type="record_execution_update",
                        target_ref="renfo d'hier",
                        target_session_id=session.id,
                        status="not_completed",
                        completed=False,
                        confidence=0.95,
                        evidence="pas eu le temps hier",
                    )
                ],
            )
            api_messages.extract_facts = lambda *args, **kwargs: []

            with self.assertLogs("fitmas.conversation_metrics", level="INFO") as logs:
                result = self.client.post("/api/v0/messages", json={"text": "J'ai pas eu le temps hier malheureusement"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        events = self.db.query(s.MemoryMutationEventRecord).order_by(s.MemoryMutationEventRecord.id).all()
        turns = repo.get_recent_conversation_turns(self.db, self.user.id, limit=1)

        self.assertIn("Note pour hier", result["assistant_message"]["text"])
        self.assertEqual(updated.completion_status, "skipped")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action_type, "record_execution_update")
        self.assertIn('"category": "execution"', turns[0].memory_writes_json)
        self.assertIn('"key": "record_execution_update"', turns[0].memory_writes_json)
        metric_line = "\n".join(logs.output)
        self.assertIn("execution_actions_per_turn=1", metric_line)
        self.assertIn("memory_actions_per_turn=0", metric_line)
        self.assertIn("pending_resolution_per_turn=0", metric_line)

    def test_execution_action_survives_blocked_plan_patch_reply(self) -> None:
        now = get_local_now(self.user.timezone)
        yesterday = (now - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        session = s.ScheduledSession(
            user_id=self.user.id,
            day=DAY_KEYS[yesterday.weekday()],
            label=day_label_fr(DAY_KEYS[yesterday.weekday()], capitalize=True),
            scheduled_date=yesterday,
            sport_type="strength",
            session_type="strength",
            session_title="Renfo 34min",
            session_goal="Support",
            duration_min=34,
            intensity="moderate",
            load_score=3,
            priority="Normal",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        try:
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="plan_patch",
                rationale="execution manquee et patch planning non essentiel",
                fitmas_message="Renfo d'hier note non fait. On garde ce matin simple.",
                execution_actions=[
                    llm.ExecutionUpdateAction(
                        type="record_execution_update",
                        target_ref="renfo d'hier",
                        target_session_id=session.id,
                        status="not_completed",
                        completed=False,
                        evidence="pas eu le temps hier",
                    )
                ],
                plan_patch=PlanPatch(
                    coach_message="On garde ce matin simple.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="lighten_day",
                            target_session_id=session.id,
                            rationale="Ne pas rattraper le renfo manque.",
                        )
                    ],
                ),
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            result = self.client.post("/api/v0/messages", json={"text": "J'ai pas eu le temps hier malheureusement"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertEqual(updated.completion_status, "skipped")
        self.assertIn("Renfo 34min", result["assistant_message"]["text"])
        self.assertIn("non faite", result["assistant_message"]["text"])
        self.assertNotIn("Je ne l'ai pas applique", result["assistant_message"]["text"])

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
        self.assertIn(skipped_key, active_keys)
        self.assertEqual(archived_keys, set())

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

    def test_no_change_reply_is_not_rewritten_by_removed_sanitizer(self) -> None:
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

        self.assertIn("40min", result["assistant_message"]["text"])
        self.assertNotIn("recalibrer", result["assistant_message"]["text"])

    def test_message_flow_consumes_structured_calibration_resolution_then_calls_llm(self) -> None:
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
        original_calibration_extract = conversation_pipeline.extract_calibration_resolution
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="Calibration integree, pas de mutation.",
                fitmas_message="OK, je note.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
            conversation_pipeline.extract_calibration_resolution = lambda *args, **kwargs: calibration_needs.CalibrationResolution(
                need_id=need.id,
                resolved=True,
                normalized_value={
                    "day": "thursday",
                    "windows": ["evening"],
                    "hard_blocked": ["morning"],
                },
                confidence=0.93,
                followup_needed=False,
                raw_summary="Plutot le soir",
            )
            result = self.client.post("/api/v0/messages", json={"text": "Plutot le soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            conversation_pipeline.extract_calibration_resolution = original_calibration_extract

        facts = self.client.get("/api/v0/facts").json()
        categories = {(fact["category"], fact["key"]) for fact in facts}

        self.assertTrue(result["assistant_message"]["text"].strip())
        self.assertEqual(result["assistant_message"]["text"], "OK, je note.")
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
        original_calibration_extract = conversation_pipeline.extract_calibration_resolution
        try:
            api_messages.decide = lambda *args, **kwargs: MutationDecision(
                mutation_type="no_change",
                rationale="Calibration integree par le LLM.",
                fitmas_message=f"OK, je note {expected_day_label}: plutot le soir.",
            )
            api_messages.extract_facts = lambda *args, **kwargs: []
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
            result = self.client.post("/api/v0/messages", json={"text": "Plutot le soir"}).json()
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            conversation_pipeline.extract_calibration_resolution = original_calibration_extract

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
        original_plan_turn = api_messages.plan_conversation_turn
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
            api_messages.plan_conversation_turn = lambda *args, **kwargs: SimpleNamespace(
                primary_intent="plan_lookup",
                secondary_intents=(),
                has_plan_mutation=False,
                model_dump=lambda mode="json": {
                    "primary_intent": "plan_lookup",
                    "secondary_intents": [],
                    "has_plan_mutation": False,
                },
            )
            result = self.client.post("/api/v0/messages", json={"text": "C'etait quoi ma plus longue sortie recente ?"}).json()
        finally:
            llm._client = original_client
            llm._request_message = original_request_message
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

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
        """Phase 3: a multi-day availability constraint emitted by
        CoachDecision.memory_actions must be persisted as a UserFact with
        category=availability, a key encoding start/end dates, and
        expires_at anchored on window_end + 1 day so it stays active for
        the whole constraint and is auto-filtered out afterwards."""
        self._create_plan_for_today()
        now = get_local_now(self.user.timezone)
        start = now.date() + timedelta(days=1)
        end = start + timedelta(days=13)  # 14-day window inclusive

        original_decide = api_messages.decide
        original_extract_facts = api_messages.extract_facts
        original_plan_turn = api_messages.plan_conversation_turn
        try:
            api_messages.extract_facts = lambda *args, **kwargs: []
            api_messages.plan_conversation_turn = lambda *args, **kwargs: None
            api_messages.decide = lambda *args, **kwargs: CoachDecision(
                response_type="no_change",
                rationale="note prise",
                fitmas_message="Bien note.",
                memory_actions=[
                    llm.AvailabilityConstraintAction(
                        type="record_availability",
                        window_text="piscine indisponible pendant 2 semaines",
                        availability="unavailable",
                        starts_on=start.isoformat(),
                        ends_on=end.isoformat(),
                        confidence=0.9,
                        evidence="je n'ai pas acces a la piscine pendant 2 semaines",
                    )
                ],
            )
            self.client.post(
                "/api/v0/messages",
                json={"text": "je n'ai pas acces a la piscine pendant 2 semaines"},
            )
        finally:
            api_messages.decide = original_decide
            api_messages.extract_facts = original_extract_facts
            api_messages.plan_conversation_turn = original_plan_turn

        facts = (
            self.db.query(s.WorkingMemoryEntry)
            .filter(s.WorkingMemoryEntry.user_id == self.user.id, s.WorkingMemoryEntry.category == "availability")
            .all()
        )
        self.assertEqual(len(facts), 1, f"expected 1 availability fact, got {[(f.category, f.key) for f in facts]}")
        fact = facts[0]
        self.assertEqual(
            fact.key,
            f"availability_{start.isoformat()}_{end.isoformat()}",
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
