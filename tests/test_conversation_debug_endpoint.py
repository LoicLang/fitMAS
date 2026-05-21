from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-conversation-debug-", suffix=".db"))
os.environ["FITMAS_ENABLE_DEBUG_ENDPOINTS"] = "1"

from fastapi.testclient import TestClient

from fitmas.app.api import routes_messages as api_messages
from fitmas import repository as repo, schema as s
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class FakeReplyComposer:
    def __init__(self, text: str = "Redis-moi le changement voulu en une phrase.") -> None:
        self.text = text

    def compose(self, *args, **kwargs):
        return SimpleNamespace(text=self.text, verified=True, fallback_used=False, reason=None)


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
        self._original_extract_facts = api_messages.extract_facts
        self._original_plan_turn = api_messages.plan_conversation_turn

        from fitmas import conversation_pipeline

        self._conversation_pipeline = conversation_pipeline
        self._original_reply_composer = conversation_pipeline._decision_reply_composer
        conversation_pipeline._decision_reply_composer = lambda: FakeReplyComposer()

    def tearDown(self) -> None:
        api_messages.extract_facts = self._original_extract_facts
        api_messages.plan_conversation_turn = self._original_plan_turn
        self._conversation_pipeline._decision_reply_composer = self._original_reply_composer
        os.environ.pop("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", None)
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

    def test_debug_endpoint_exposes_removed_provider_trace(self) -> None:
        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []

        response = self.client.post(
            "/ops/conversation/debug",
            json={
                "text": "Je fais quoi ce soir ?",
                "client_message_key": "debug-provider-removed-1",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        debug = payload["debug"]
        self.assertEqual(debug["kind"], "conversation")
        self.assertEqual(debug["turn"]["response_mode"], "canonical_provider_clarification")
        self.assertEqual(debug["context"]["legacy_decide"]["reason"], "coach_decision_provider_removed")
        self.assertEqual(debug["flow"]["final"]["message"], "Redis-moi le changement voulu en une phrase.")

    def test_debug_endpoint_exposes_canonical_understanding_before_removed_provider_trace(self) -> None:
        from fitmas.decision import CoachUnderstanding, ClarificationNeed
        from fitmas.decision import understanding_runtime

        api_messages.plan_conversation_turn = lambda *args, **kwargs: None
        api_messages.extract_facts = lambda *args, **kwargs: []

        class FakeService:
            def understand(self, request):
                return CoachUnderstanding(
                    intent="clarification",
                    confidence=0.88,
                    user_summary="besoin de precision",
                    extracted_signals=(),
                    requested_change=None,
                    pending_resolution=None,
                    clarification_need=ClarificationNeed(
                        reason="target_missing",
                        missing_fields=("target",),
                        question_intent="ask_target",
                    ),
                )

        original_service = understanding_runtime.LLMUnderstandingService
        try:
            understanding_runtime.LLMUnderstandingService = lambda: FakeService()
            os.environ["FITMAS_UNDERSTANDING_RUNTIME_SHADOW"] = "1"
            response = self.client.post(
                "/ops/conversation/debug",
                json={
                    "text": "change la seance",
                    "client_message_key": "debug-understanding-removed-provider-1",
                },
            )
        finally:
            understanding_runtime.LLMUnderstandingService = original_service

        self.assertEqual(response.status_code, 200)
        context = response.json()["debug"]["context"]
        self.assertEqual(context["canonical_understanding"]["intent"], "clarification")
        self.assertEqual(context["legacy_decide"]["reason"], "coach_decision_provider_removed")


if __name__ == "__main__":
    unittest.main()
