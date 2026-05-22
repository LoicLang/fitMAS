from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from fitmas.domain.coaching import repo_conversation
from fitmas.domain.execution import repository as execution_repo
from fitmas.domain.planning import repository as planning_repo
from fitmas.domain.planning import template_repository as template_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-tests-", suffix=".db"))

from fastapi.testclient import TestClient

from fitmas.app.api import routes_messages as api_messages
import fitmas.decision.conversation_pipeline as conversation_pipeline
import fitmas.domain.planning.patch_mutation_service as plan_mutation_service
from fitmas.api import app
from fitmas.decision.conversation_contract import (
    ConversationTurnOutcome,
)
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.decision import PendingResolution
from fitmas.decision.command_actions import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
)
from fitmas.decision import command_application
from fitmas.decision import plan_patch_reply
from fitmas.decision import pending_resolution as conversation_pending_bridge
from fitmas.models import Extraction
from fitmas.domain.planning.mutation_permissions import serialize_plan_patch_confirmation
from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.domain.planning.session_actions import move_session
from fitmas.domain.athlete.training_load import compute_ctl_atl_tsb, estimate_tss
from fitmas import schema as s
from fitmas.core.time_context import DAY_KEYS, day_label_fr, get_local_now
from fitmas.domain.planning.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


def _pending(
    resolution_type: str,
    *,
    reason: str | None = None,
    selected_candidate_id: str | None = None,
    requested_changes: str | None = None,
    question: str | None = None,
) -> PendingResolution:
    return PendingResolution(
        type=resolution_type,
        reason=reason,
        selected_candidate_id=selected_candidate_id,
        requested_changes=requested_changes,
        question=question,
    )


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

    def _assert_legacy_mutation_disabled(self, result: dict, *, mutation_type: str) -> s.ConversationTurnRecord:
        turns = repo_conversation.get_recent_conversation_turns(self.db, self.user.id, limit=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].response_mode, "legacy_decision_contract_disabled")
        self.assertEqual(turns[0].mutation_type, mutation_type)
        self.assertFalse(turns[0].mutation_applied)
        self.assertFalse(turns[0].pending_confirmation)
        self.assertIn("ancienne forme de decision", result["assistant_message"]["text"].lower())
        return turns[0]

    def _create_plan_for_today(self) -> tuple[s.WeeklyPlan, s.ScheduledSession]:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        plan = template_repo.replace_plan(
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
        session = planning_repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
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
        plan = template_repo.replace_plan(
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
        sessions = [planning_repo.to_pydantic_scheduled_session(x) for x in planning_repo.get_scheduled_sessions(self.db, self.user.id, limit=10)]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].sport_type, "rest")
        self.assertEqual(sessions[0].completion_status, "adapted")
        self.assertEqual(sessions[1].session_title, "Footing facile")
        self.assertEqual(sessions[1].id, session.id)
        self.assertEqual(sessions[1].scheduled_date, (source_date + timedelta(days=8)).isoformat())

    def test_read_models_expose_load_band_and_week_meta(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        template_repo.replace_plan(
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
        self.assertEqual(week.json()["runtime_role"], "scheduled_runtime")
        self.assertEqual(week.json()["total_weeks"], 1)
        self.assertEqual(week.json()["mesocycle_week"], 1)
        self.assertFalse(week.json()["is_deload"])
        self.assertEqual(week.json()["days"][0]["load_band"], "hard")

        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["load_band"], "hard")

        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()[0]["load_band"], "hard")

    def test_week_endpoint_reads_scheduled_session_runtime_truth(self) -> None:
        plan, session = self._create_plan_for_today()
        day_plan = template_repo.get_day_plan(self.db, plan.id, session.day)
        self.assertIsNotNone(day_plan)
        self.assertEqual(day_plan.sport_type, "running")

        session.sport_type = "rest"
        session.session_type = "rest"
        session.session_title = "Journee flexible"
        session.session_goal = "Absorber l'imprevu"
        session.session_note = "inondations"
        session.session_description = "Repos adapte apres imprevu."
        session.duration_min = None
        session.intensity = "easy"
        session.load_score = 0
        session.priority = "Flexible"
        session.nutrition_focus = ""
        session.flexibility = "flexible"
        session.completion_status = "adapted"
        self.db.commit()

        response = self.client.get("/api/v0/week")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["runtime_role"], "scheduled_runtime")
        self.assertEqual(payload["days"][0]["sport_type"], "rest")
        self.assertEqual(payload["days"][0]["session_title"], "Journee flexible")
        self.assertEqual(payload["days"][0]["completion_status"], "adapted")

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
        execution_repo.add_activity(
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
        planning_repo.mark_scheduled_session_completed(self.db, session.id)

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

    def test_active_pending_lookup_requires_unique_pending_row(self) -> None:
        for index in range(2):
            self.db.add(
                s.PendingMutationConfirmation(
                    user_id=self.user.id,
                    impact_level="high",
                    reason=f"manual_{index}",
                    mutation_type="plan_patch",
                    summary=f"pending {index}",
                    source_text="manual fixture",
                    decision_json="{}",
                    expires_at=datetime.now() + timedelta(minutes=10),
                )
            )
        self.db.commit()

        active_pending = repo_conversation.get_active_pending_mutation_confirmation(self.db, self.user.id)
        rows = (
            self.db.query(s.PendingMutationConfirmation)
            .filter(s.PendingMutationConfirmation.user_id == self.user.id)
            .order_by(s.PendingMutationConfirmation.id)
            .all()
        )

        self.assertIsNone(active_pending)
        self.assertEqual([row.status for row in rows], ["pending", "pending"])

    def test_pending_accept_recheck_blocks_weak_wait_turn(self) -> None:
        _, session = self._create_plan_for_today()
        target_date = (get_local_now(self.user.timezone).date() + timedelta(days=2)).isoformat()
        patch = PlanPatch(
            coach_message="Je deplace la seance.",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=target_date,
                    rationale="Demande utilisateur a confirmer.",
                )
            ],
        )
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="week_coherence_requires_confirmation",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="le modele principal a sur-interprete le tour",
            fitmas_message="Je garde la proposition ouverte.",
            pending_resolution=_pending("accept_pending"),
        )

        original_verify = conversation_pending_bridge.verify_pending_accept_resolution
        try:
            conversation_pending_bridge.verify_pending_accept_resolution = lambda **kwargs: "ignore"
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=decision,
                canonical_understanding=None,
                pending_confirmation=pending,
                user_text="j'attends",
            )
        finally:
            conversation_pending_bridge.verify_pending_accept_resolution = original_verify

        self.db.expire_all()
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        refreshed_session = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_ignore")
        self.assertFalse(outcome.mutation_applied)
        self.assertTrue(outcome.pending_confirmation)
        self.assertEqual(outcome.pending_confirmation_id, pending.id)
        self.assertEqual(refreshed_pending.status, "pending")
        self.assertNotEqual(refreshed_session.scheduled_date.date().isoformat(), target_date)

    def test_pending_accept_recheck_allows_clear_acceptance(self) -> None:
        _, session = self._create_plan_for_today()
        target_date = (get_local_now(self.user.timezone).date() + timedelta(days=2)).isoformat()
        patch = PlanPatch(
            coach_message="Je deplace la seance.",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=target_date,
                    rationale="Demande utilisateur a confirmer.",
                )
            ],
        )
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="week_coherence_requires_confirmation",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="acceptation pending comprise",
            fitmas_message="C'est confirme. Je l'applique.",
            pending_resolution=_pending("accept_pending"),
        )

        original_verify = conversation_pending_bridge.verify_pending_accept_resolution
        try:
            conversation_pending_bridge.verify_pending_accept_resolution = lambda **kwargs: "accept_pending"
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=decision,
                canonical_understanding=None,
                pending_confirmation=pending,
                user_text="oui confirme",
            )
        finally:
            conversation_pending_bridge.verify_pending_accept_resolution = original_verify

        self.db.expire_all()
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        refreshed_session = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_accepted")
        self.assertTrue(outcome.mutation_applied)
        self.assertEqual(refreshed_pending.status, "accepted")
        self.assertEqual(refreshed_session.scheduled_date.date().isoformat(), target_date)

    def test_pending_resolution_alias_confirm_is_canonicalized_before_application(self) -> None:
        _, session = self._create_plan_for_today()
        target_date = (get_local_now(self.user.timezone).date() + timedelta(days=2)).isoformat()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="week_coherence_requires_confirmation",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Je deplace la seance.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=target_date,
                            rationale="Demande utilisateur a confirmer.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="acceptation pending comprise avec alias provider",
            fitmas_message="C'est confirme. Je l'applique.",
            pending_resolution=_pending("confirm"),
        )

        original_verify = conversation_pending_bridge.verify_pending_accept_resolution
        try:
            conversation_pending_bridge.verify_pending_accept_resolution = lambda **kwargs: "accept_pending"
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=decision,
                canonical_understanding=None,
                pending_confirmation=pending,
                user_text="oui je confirme si tu penses que c'est propre",
            )
        finally:
            conversation_pending_bridge.verify_pending_accept_resolution = original_verify

        self.db.expire_all()
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        refreshed_session = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_accepted")
        self.assertTrue(outcome.mutation_applied)
        self.assertEqual(refreshed_pending.status, "accepted")
        self.assertEqual(refreshed_session.scheduled_date.date().isoformat(), target_date)

    def test_unknown_pending_resolution_type_becomes_clarification_artifact(self) -> None:
        artifact = conversation_pending_bridge.pending_resolution_from_sources(
            decision_artifact=SimpleNamespace(pending_resolution=_pending("provider_specific_yesish")),
            canonical_understanding=None,
        )

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.type, "needs_clarification")
        self.assertIn("invalid_pending_resolution_type", artifact.reason)

    def test_pending_reject_recheck_blocks_ambiguous_rejection(self) -> None:
        _, session = self._create_plan_for_today()
        patch = PlanPatch(
            coach_message="Je deplace la seance.",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=(session.scheduled_date.date() + timedelta(days=2)).isoformat(),
                    rationale="Demande utilisateur a confirmer.",
                )
            ],
        )
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="week_coherence_requires_confirmation",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="le modele principal a sur-interprete le non",
            fitmas_message="Je ne l'applique pas.",
            pending_resolution=_pending("reject_pending"),
        )

        original_verify = conversation_pending_bridge.verify_pending_accept_resolution
        try:
            conversation_pending_bridge.verify_pending_accept_resolution = lambda **kwargs: "ignore"
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=decision,
                canonical_understanding=None,
                pending_confirmation=pending,
                user_text="non j'etais indispo aujourd'hui mais demain je suis dispo",
            )
        finally:
            conversation_pending_bridge.verify_pending_accept_resolution = original_verify

        self.db.expire_all()
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_ignore")
        self.assertTrue(outcome.pending_confirmation)
        self.assertEqual(outcome.pending_confirmation_id, pending.id)
        self.assertEqual(refreshed_pending.status, "pending")

    def test_pending_accept_recheck_mismatch_with_plan_mutation_falls_through(self) -> None:
        _, session = self._create_plan_for_today()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="adaptation a confirmer",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="running demain",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Je deplace la seance.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                            rationale="Adaptation a confirmer.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="acceptation surestimee",
            fitmas_message="Je le fais.",
            pending_resolution=_pending("accept_pending"),
        )
        turn_plan = SimpleNamespace(
            primary_intent="plan_mutation",
            secondary_intents=("availability_constraint",),
            has_plan_mutation=True,
        )

        original_verify = conversation_pending_bridge.verify_pending_accept_resolution
        try:
            conversation_pending_bridge.verify_pending_accept_resolution = lambda **kwargs: "ignore"
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=decision,
                canonical_understanding=None,
                pending_confirmation=pending,
                user_text="non j'etais indispo aujourd'hui mais demain je suis dispo",
                turn_plan=turn_plan,
            )
        finally:
            conversation_pending_bridge.verify_pending_accept_resolution = original_verify

        self.assertIsNone(outcome)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertEqual(refreshed_pending.status, "pending")

    def test_pending_ignore_does_not_swallow_new_plan_patch(self) -> None:
        _, session = self._create_plan_for_today()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="ancienne proposition",
            mutation_type="plan_patch",
            summary="ancienne proposition",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Ancienne proposition.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=(session.scheduled_date.date() + timedelta(days=2)).isoformat(),
                            rationale="Ancienne proposition.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="requires_confirmation",
            rationale="nouvelle proposition structuree",
            fitmas_message="Je te propose une nouvelle option.",
            confirmation_reason="nouvelle proposition",
            plan_patch=PlanPatch(
                coach_message="Nouvelle proposition.",
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=(session.scheduled_date.date() + timedelta(days=3)).isoformat(),
                        rationale="Nouvelle proposition.",
                    )
                ],
            ),
            pending_resolution=_pending("ignore"),
        )

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="readapte plutot la semaine",
        )

        self.assertIsNone(outcome)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertEqual(refreshed_pending.status, "pending")

    def test_pending_modify_with_plan_mutation_falls_through_to_adaptation(self) -> None:
        _, session = self._create_plan_for_today()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="ancienne proposition",
            mutation_type="plan_patch",
            summary="ancienne proposition",
            source_text="deplace vendredi",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Ancienne proposition.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=(session.scheduled_date.date() + timedelta(days=2)).isoformat(),
                            rationale="Ancienne proposition.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        decision = SimpleNamespace(
            response_type="reply",
            rationale="la pending doit laisser passer la nouvelle demande planning",
            fitmas_message="Je garde la proposition en attente.",
            pending_resolution=_pending(
                "modify_pending",
                requested_changes="readapter la semaine",
            ),
        )
        turn_plan = SimpleNamespace(
            primary_intent="plan_mutation",
            secondary_intents=(),
            has_plan_mutation=True,
        )

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="ok readapte la semaine alors",
            turn_plan=turn_plan,
        )

        self.assertIsNone(outcome)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertEqual(refreshed_pending.status, "pending")

    def test_old_mixed_plan_adaptation_hook_is_absent(self) -> None:
        self.assertFalse(
            hasattr(conversation_pipeline, "_should_try_mixed_plan_adaptation_after_decide")
        )

    def test_pending_pre_adaptation_gate_only_allows_modify_pending(self) -> None:
        self.assertTrue(conversation_pending_bridge.pending_pre_adaptation_allows("modify_pending"))
        self.assertFalse(conversation_pending_bridge.pending_pre_adaptation_allows("ignore"))
        self.assertFalse(conversation_pending_bridge.pending_pre_adaptation_allows("needs_clarification"))
        self.assertFalse(conversation_pending_bridge.pending_pre_adaptation_allows("accept_pending"))

    def test_pending_survives_clarification_outcome(self) -> None:
        _, session = self._create_plan_for_today()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="adaptation a confirmer",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="readapte la semaine",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Je deplace la seance.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                            rationale="Adaptation a confirmer.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text="Tu parles bien de la seance de running ?",
            response_mode="plan_patch_clarification",
            mutation_applied=False,
        )

        self.assertTrue(conversation_pending_bridge.outcome_keeps_pending_confirmation(outcome, pending))

    def test_non_mutating_close_turn_keeps_active_pending(self) -> None:
        _, session = self._create_plan_for_today()
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="adaptation a confirmer",
            mutation_type="plan_patch",
            summary="deplacer la seance",
            source_text="readapte la semaine",
            decision_json=serialize_plan_patch_confirmation(
                PlanPatch(
                    coach_message="Je deplace la seance.",
                    operations=[
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                            rationale="Adaptation a confirmer.",
                        )
                    ],
                )
            ),
            expires_at=datetime.now() + timedelta(minutes=10),
        )
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text="D'accord, je reste en attente de ta validation.",
            response_mode="reply",
            mutation_applied=False,
        )
        turn_plan = SimpleNamespace(primary_intent="close_turn")

        conversation_pending_bridge.keep_pending_for_non_mutating_turn(
            outcome=outcome,
            turn_plan=turn_plan,
            pending_confirmation=pending,
        )

        self.assertTrue(outcome.pending_confirmation)
        self.assertEqual(outcome.pending_confirmation_id, pending.id)
        self.assertTrue(conversation_pending_bridge.outcome_keeps_pending_confirmation(outcome, pending))

    def test_plan_patch_turn_defers_conflicting_not_completed_execution_action(self) -> None:
        _, session = self._create_plan_for_today()
        decision = SimpleNamespace(
            response_type="requires_confirmation",
            rationale="Dispo corrigee et adaptation planning a confirmer.",
            fitmas_message="Je note demain dispo et je te propose de deplacer la seance.",
            confirmation_reason="adaptation semaine",
            plan_patch=PlanPatch(
                coach_message="Je deplace la seance demain.",
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                        rationale="Disponibilite corrigee.",
                    )
                ],
            ),
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="demain disponible",
                    availability="available",
                    starts_on=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                    ends_on=(session.scheduled_date.date() + timedelta(days=1)).isoformat(),
                    confidence=0.9,
                    evidence="demain je suis dispo",
                ),
            ),
            execution_actions=(
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref="seance a reprogrammer",
                    target_session_id=session.id,
                    status="not_completed",
                    completed=False,
                    confidence=0.86,
                    evidence="indispo aujourd'hui",
                ),
            ),
        )
        memory_writes: list[dict] = []

        result = command_application.apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            turn_memory_writes=memory_writes,
        )

        self.db.expire_all()
        refreshed = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertEqual(result["memory_applied"], 1)
        self.assertEqual(result["execution_applied"], 0)
        self.assertEqual(result["execution_deferred"], 1)
        self.assertEqual(refreshed.completion_status, "planned")
        self.assertIn(
            {
                "category": "execution",
                "key": "record_execution_update",
                "value": "deferred=1",
                "source": "coach_decision",
                "action": "deferred",
            },
            memory_writes,
        )

    def test_plan_patch_turn_defers_conflicting_execution_action_from_turn_plan_availability(self) -> None:
        _, session = self._create_plan_for_today()
        tomorrow = session.scheduled_date.date() + timedelta(days=1)
        decision = SimpleNamespace(
            response_type="requires_confirmation",
            rationale="Dispo typée dans le turn planner et adaptation planning a confirmer.",
            fitmas_message="Je note demain dispo et je te propose de deplacer la seance.",
            confirmation_reason="adaptation semaine",
            plan_patch=PlanPatch(
                coach_message="Je deplace la seance demain.",
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=tomorrow.isoformat(),
                        rationale="Disponibilite corrigee.",
                    )
                ],
            ),
            execution_actions=(
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref="seance a reprogrammer",
                    target_session_id=session.id,
                    status="not_completed",
                    completed=False,
                    confidence=0.86,
                    evidence="indispo aujourd'hui",
                ),
            ),
        )
        turn_plan = SimpleNamespace(
            availability_constraint={
                "availability": "available",
                "sport_type": None,
                "scope": "general",
                "starts_on": tomorrow.isoformat(),
                "ends_on": tomorrow.isoformat(),
            },
            confidence=0.9,
        )
        memory_writes: list[dict] = []

        result = command_application.apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            turn_memory_writes=memory_writes,
            turn_plan=turn_plan,
        )

        self.db.expire_all()
        refreshed = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertEqual(result["memory_applied"], 1)
        self.assertEqual(result["execution_applied"], 0)
        self.assertEqual(result["execution_deferred"], 1)
        self.assertEqual(refreshed.completion_status, "planned")

    def test_turn_plan_available_artifact_resolves_stale_unavailability_even_if_decision_is_limited(self) -> None:
        tomorrow = get_local_now(self.user.timezone).date() + timedelta(days=1)
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="availability",
                key=f"unavailable_general_{tomorrow.isoformat()}_{tomorrow.isoformat()}",
                value="indisponible demain",
                source="conversation",
                confidence=0.8,
                confirmed=True,
                active=True,
                status="open",
                signal_kind="availability_unavailable",
                valid_from=datetime.combine(tomorrow, datetime.min.time()),
                valid_until=datetime.combine(tomorrow + timedelta(days=1), datetime.min.time()),
            )
        )
        self.db.commit()
        decision = SimpleNamespace(
            response_type="reply",
            rationale="correction disponibilite",
            fitmas_message="OK, demain est dispo.",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="indispo aujourd'hui mais dispo demain",
                    availability="limited",
                    starts_on=(tomorrow - timedelta(days=1)).isoformat(),
                    ends_on=tomorrow.isoformat(),
                    confidence=0.9,
                    evidence="indispo aujourd'hui mais dispo demain",
                ),
            ),
        )
        turn_plan = SimpleNamespace(
            availability_constraint={
                "availability": "available",
                "sport_type": None,
                "scope": "general",
                "starts_on": tomorrow.isoformat(),
                "ends_on": tomorrow.isoformat(),
            },
            confidence=0.9,
        )
        memory_writes: list[dict] = []

        result = command_application.apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            turn_memory_writes=memory_writes,
            turn_plan=turn_plan,
        )

        self.db.expire_all()
        stale_fact = (
            self.db.query(s.UserFact)
            .filter(s.UserFact.key == f"unavailable_general_{tomorrow.isoformat()}_{tomorrow.isoformat()}")
            .one()
        )

        self.assertGreaterEqual(result["memory_applied"], 2)
        self.assertEqual(stale_fact.status, "resolved")
        self.assertFalse(stale_fact.active)
        self.assertEqual(stale_fact.resolution_reason, "availability_available_overlap")

    def test_expired_pending_accept_resolution_does_not_apply_patch(self) -> None:
        _, session = self._create_plan_for_today()
        patch = PlanPatch(
            coach_message="Je reduis la seance.",
            operations=[
                PlanPatchOperation(
                    operation_type="update_session",
                    target_session_id=session.id,
                    new_duration_min=25,
                    new_intensity="easy",
                    rationale="Demande utilisateur a confirmer.",
                )
            ],
        )
        pending = repo_conversation.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="week_coherence_requires_confirmation",
            mutation_type="plan_patch",
            summary="reduire la seance",
            source_text="alleger demain",
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
        )
        decision = SimpleNamespace(
            response_type="no_change",
            rationale="acceptation pending comprise",
            fitmas_message="C'est confirme. Je l'applique.",
            pending_resolution=_pending("accept_pending"),
        )

        outcome = conversation_pending_bridge.accept_pending_confirmation(
            db=self.db,
            user=self.user,
            decision_artifact=decision,
            pending_confirmation=pending,
        )

        self.db.expire_all()
        refreshed_session = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)

        self.assertEqual(outcome.response_mode, "pending_expired")
        self.assertFalse(outcome.mutation_applied)
        self.assertEqual(refreshed_session.duration_min, 40)
        self.assertEqual(refreshed_pending.status, "expired")

    def test_post_event_reply_falls_back_when_composer_claims_before_date_as_destination(self) -> None:
        service_result = plan_mutation_service.PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
            mutation_result=plan_mutation_service.PlanMutationServiceResult(
                plan_id=0,
                applied_count=1,
                attempted_count=1,
                event_count=1,
                applied_events=(
                    plan_mutation_service.PlanAppliedMutationEvent(
                        command_type="move_session",
                        user_visible_summary="Lundi: Recuperation mobilite. 30 min.",
                        target_session_id=3,
                        before_snapshot={
                            "scheduled_date": "2026-05-22T08:00:00",
                            "session_title": "Recuperation mobilite",
                            "sport_type": "strength",
                            "duration_min": 30,
                        },
                        after_snapshot={
                            "scheduled_date": "2026-05-18T00:00:00",
                            "session_title": "Recuperation mobilite",
                            "sport_type": "strength",
                            "duration_min": 30,
                        },
                    ),
                ),
            ),
        )
        original_compose = plan_patch_reply.final_reply.compose_final_reply
        original_verify = plan_patch_reply.final_reply.verify_post_event_reply
        try:
            plan_patch_reply.final_reply.compose_final_reply = (
                lambda *args, **kwargs: "Ta seance passe finalement au vendredi. Lundi sera plus leger."
            )
            plan_patch_reply.final_reply.verify_post_event_reply = lambda reply, context, **kwargs: reply

            reply = plan_patch_reply._applied_plan_patch_reply(
                service_result,
                fallback="fallback",
            )
        finally:
            plan_patch_reply.final_reply.compose_final_reply = original_compose
            plan_patch_reply.final_reply.verify_post_event_reply = original_verify

        self.assertEqual(
            reply,
            "J'ai deplace Recuperation mobilite du 2026-05-22 (vendredi) au 2026-05-18 (lundi).",
        )

    def test_conversation_turn_serializes_datetime_memory_writes(self) -> None:
        row = repo_conversation.add_conversation_turn(
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

    def test_low_signal_classifier_removed_from_runtime(self) -> None:
        self.assertFalse(hasattr(api_messages, "_maybe_low_signal_label"))

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

        from fitmas.decision.conversation_context import build_conversation_context

        scheduled_payloads = [
            {
                "id": row.id,
                "day": row.day,
                "scheduled_date": row.scheduled_date,
                "sport_type": row.sport_type,
                "session_title": row.session_title,
                "completion_status": row.completion_status,
            }
            for row in planning_repo.get_scheduled_sessions_between_dates(
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
        execution_repo.add_activity(
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
