from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.legacy.decision.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    non_completion_summary_for_prompt,
    temporal_summary_for_prompt,
)


class ConversationContextTest(unittest.TestCase):
    def test_builds_context_without_parsing_user_text(self) -> None:
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
            signals=[
                {"kind": "big_session_done", "severity": "info", "summary": "Grosse seance recente."},
                {"kind": "missed_key_session", "severity": "warning", "summary": "Seance cle ratee."},
            ],
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
        )

        self.assertEqual(context.temporal_resolution.primary_reference, "unspecified")
        self.assertFalse(hasattr(context, "recent_activity_claim"))
        self.assertFalse(hasattr(context, "non_completion_claim"))
        self.assertIn("Retrouver mon niveau running", "\n".join(context.selected_facts))
        self.assertEqual(context.selected_signals[0]["kind"], "missed_key_session")
        self.assertIn("execution_status: planned_pending", execution_summary_for_prompt(context))
        self.assertIn("reference principale: unspecified", temporal_summary_for_prompt(context))
        self.assertEqual(activity_claim_summary_for_prompt(context), "")

    def test_build_claim_memory_updates_noops_in_llm_first_phase0(self) -> None:
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

        self.assertEqual(updates, [])

    def test_non_completion_summary_noops_in_llm_first_phase0(self) -> None:
        context = build_conversation_context(
            user_text="Je n'ai pas couru hier",
            conversation_history=[],
            timezone_name="Europe/Paris",
            scheduled_sessions=[],
            activities=[],
            active_facts=[],
            now=datetime.fromisoformat("2026-03-30T08:00:00+02:00"),
        )

        summary = non_completion_summary_for_prompt(context)

        self.assertEqual(summary, "")


if __name__ == "__main__":
    unittest.main()
