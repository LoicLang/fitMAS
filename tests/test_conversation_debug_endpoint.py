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
from fitmas import schema as s
from fitmas.api import app
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import CoachDecision
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


if __name__ == "__main__":
    unittest.main()
