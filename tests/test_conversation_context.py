from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    temporal_summary_for_prompt,
)


class ConversationContextTest(unittest.TestCase):
    def test_builds_grounded_context_bundle(self) -> None:
        context = build_conversation_context(
            user_text="J'ai fait 30 min mais c'etait hier",
            conversation_history=[{"role": "user", "text": "J'ai couru aujourd'hui"}],
            timezone_name="Europe/Paris",
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T07:00:00+01:00",
                    "sport_type": "swimming",
                    "session_title": "Natation",
                    "duration_min": 60,
                    "completion_status": "planned",
                }
            ],
            activities=[],
            active_facts=[
                {
                    "category": "goal",
                    "key": "running_focus",
                    "value": "Retrouver mon niveau running",
                    "source": "conversation",
                    "confidence": 0.8,
                    "confirmed": True,
                    "active": True,
                }
            ],
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        self.assertEqual(context.temporal_resolution.primary_reference, "yesterday")
        self.assertEqual(context.recent_activity_claim.sport_type, "running")
        self.assertEqual(context.recent_activity_claim.duration_min, 30)
        self.assertIn("Retrouver mon niveau running", "\n".join(context.selected_facts))
        self.assertIn("execution_status: planned_pending", execution_summary_for_prompt(context))
        self.assertIn("reference principale: yesterday", temporal_summary_for_prompt(context))
        self.assertIn("sport: running", activity_claim_summary_for_prompt(context))

    def test_build_claim_memory_updates_archives_previous_claim_on_correction(self) -> None:
        context = build_conversation_context(
            user_text="Non c'etait hier",
            conversation_history=[{"role": "user", "text": "J'ai couru aujourd'hui 30 min"}],
            timezone_name="Europe/Paris",
            scheduled_sessions=[],
            activities=[],
            active_facts=[],
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        updates = build_claim_memory_updates(
            context,
            activities=[],
            timezone_name="Europe/Paris",
            user_text="Non c'etait hier",
        )

        self.assertEqual(len(updates), 2)
        actions = {payload["action"] for payload in updates}
        self.assertEqual(actions, {"upsert", "archive"})


if __name__ == "__main__":
    unittest.main()
