from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-conversation-debug-", suffix=".db"))
os.environ["FITMAS_ENABLE_DEBUG_ENDPOINTS"] = "1"

from fastapi.testclient import TestClient

import fitmas.api_messages as api_messages
import fitmas.final_reply as final_reply
import fitmas.plan_mutation_service as plan_mutation_service
from fitmas import repository as repo, schema as s
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.decision_contracts import CoachDecision, MutationDecision
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now
from fitmas.week_coherence import WeekCoherenceReview


def _valid_week_review(*args, **kwargs) -> WeekCoherenceReview:
    return WeekCoherenceReview(
        status="valid",
        sport_quality="good",
        confidence=0.86,
        summary="review valide",
        findings=(),
        suggested_adjustments=(),
        recommended_policy="commit_original",
    )


class ConversationDebugEndpointTest(unittest.TestCase):
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
        self._original_decide = api_messages.decide
        self._original_extract_facts = api_messages.extract_facts
        self._original_plan_turn = api_messages.plan_conversation_turn
        self._original_compose_no_change = final_reply.compose_no_change_reply
        self._original_week_review = plan_mutation_service.review_week_coherence_with_llm
        plan_mutation_service.review_week_coherence_with_llm = _valid_week_review

    def tearDown(self) -> None:
        api_messages.decide = self._original_decide
        api_messages.extract_facts = self._original_extract_facts
        api_messages.plan_conversation_turn = self._original_plan_turn
        final_reply.compose_no_change_reply = self._original_compose_no_change
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

    def test_debug_message_endpoint_exposes_normalized_conversation_flow(self) -> None:
        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []
        api_messages.decide = lambda *args, **kwargs: CoachDecision(
            response_type="no_change",
            rationale="Lecture simple.",
            fitmas_message="Brouillon brut a reformuler.",
        )
        final_reply.compose_no_change_reply = lambda **_kwargs: "Phrase finale propre."

        response = self.client.post(
            "/ops/conversation/debug",
            json={
                "text": "Je fais quoi ce soir ?",
                "client_message_key": "debug-conversation-flow-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["message"], "Phrase finale propre.")
        debug = payload["debug"]
        self.assertEqual(debug["kind"], "conversation")
        self.assertEqual(debug["turn"]["response_mode"], "no_change_composed")
        flow = debug["flow"]
        self.assertIn("turn_plan", flow["truth"])
        self.assertEqual(flow["draft"]["fitmas_message"], "Brouillon brut a reformuler.")
        self.assertEqual(flow["composer"]["capability"], "no_change")
        self.assertEqual(flow["composer"]["draft"], "Brouillon brut a reformuler.")
        self.assertEqual(flow["composer"]["output"], "Phrase finale propre.")
        self.assertEqual(flow["decision"]["response_mode"], "no_change_composed")
        self.assertEqual(flow["final"]["message"], "Phrase finale propre.")
        self.assertEqual(debug["context"]["coach_decision_action_result"]["command_source"], "coach_decision")

    def test_debug_message_endpoint_exposes_canonical_understanding_when_shadow_enabled(self) -> None:
        from fitmas.decision import CoachUnderstanding
        from fitmas.legacy import conversation_understanding_bridge

        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []
        api_messages.decide = lambda *args, **kwargs: CoachDecision(
            response_type="no_change",
            rationale="Lecture simple.",
            fitmas_message="Brouillon brut.",
        )

        class FakeService:
            def understand(self, request):
                return CoachUnderstanding(
                    intent="plan_lookup",
                    confidence=0.88,
                    user_summary="lookup",
                    extracted_signals=(),
                    requested_change=None,
                    pending_resolution=None,
                    clarification_need=None,
                )

        original_service = conversation_understanding_bridge.LLMUnderstandingService
        try:
            conversation_understanding_bridge.LLMUnderstandingService = lambda: FakeService()
            os.environ["FITMAS_UNDERSTANDING_RUNTIME_SHADOW"] = "1"
            response = self.client.post(
                "/ops/conversation/debug",
                json={
                    "text": "redonne le plan actuel",
                    "client_message_key": "debug-understanding-shadow-1",
                },
            )
        finally:
            conversation_understanding_bridge.LLMUnderstandingService = original_service
            os.environ.pop("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", None)

        self.assertEqual(response.status_code, 200)
        context = response.json()["debug"]["context"]
        self.assertEqual(context["canonical_understanding"]["intent"], "plan_lookup")

    def test_debug_message_endpoint_exposes_pending_confirmation_artifact(self) -> None:
        _, session = self._create_plan_for_today()
        session.priority = "Seance cle"
        self.db.commit()
        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []
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

        response = self.client.post(
            "/ops/conversation/debug",
            json={
                "text": "Tu peux remplacer ma seance ?",
                "client_message_key": "debug-pending-flow-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        flow = response.json()["debug"]["flow"]
        runtime = flow["runtime"]
        self.assertFalse(runtime["pending_confirmation"])
        self.assertIsNone(runtime["pending_confirmation_id"])
        self.assertIsNone(runtime["pending_confirmation_record"])
        self.assertEqual(runtime["response_mode"], "legacy_decision_contract_disabled")
        self.assertEqual(flow["decision"]["pending_confirmation_id"], None)
        self.assertEqual(flow["composer"]["capability"], "legacy_decision_contract_disabled")
        self.assertEqual(flow["composer"]["source"], "runtime_no_mutation")
        self.assertEqual(flow["composer"]["output"], flow["final"]["message"])

    def test_debug_message_endpoint_exposes_plan_mutation_events(self) -> None:
        _, session = self._create_plan_for_today()
        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []
        api_messages.decide = lambda *args, **kwargs: MutationDecision(
            mutation_type="lighten_day",
            target_session_id=session.id,
            rationale="On leve le pied aujourd'hui.",
            fitmas_message="On allege aujourd'hui. Tu recuperes.",
        )

        response = self.client.post(
            "/ops/conversation/debug",
            json={
                "text": "Tu peux me simplifier la seance ?",
                "client_message_key": "debug-mutation-flow-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        flow = response.json()["debug"]["flow"]
        runtime = flow["runtime"]
        events = runtime["plan_mutation_events"]
        self.assertFalse(runtime["mutation_applied"])
        self.assertEqual(events, [])
        self.assertEqual(runtime["response_mode"], "legacy_decision_contract_disabled")
        self.assertEqual(flow["composer"]["capability"], "legacy_decision_contract_disabled")
        self.assertEqual(flow["composer"]["source"], "runtime_no_mutation")
        self.assertEqual(flow["composer"]["output"], flow["final"]["message"])


if __name__ == "__main__":
    unittest.main()
