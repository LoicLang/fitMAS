from __future__ import annotations

import unittest

from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.llm_prompt_builder import build_conversation_prompt_bundle


class ConversationPromptBuilderTest(unittest.TestCase):
    def test_builds_cached_system_block_and_dynamic_prompt(self) -> None:
        bundle = build_conversation_prompt_bundle(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=2, include_plan_summary=False),
            time_block="Nous sommes mardi 2026-04-01.",
            plan_summary="Legacy plan",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[
                {"role": "user", "text": "Salut"},
                {"role": "agent", "text": "Salut."},
                {"role": "user", "text": "Jeudi c'est quoi deja ?"},
            ],
            coach_context={
                "coach_name": "FitMAS",
                "coach_style": "direct",
                "coach_relationship": "coach",
                "coach_do": "dire vrai",
                "coach_dont": "surjouer",
                "coach_soul": "calme",
                "today_session_id": 12,
            },
            selected_facts=["[constraint] Mardi soir fragile"],
        )

        self.assertEqual(bundle.system[0]["type"], "text")
        self.assertEqual(bundle.system[0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(bundle.system[0]["cache_control"]["ttl"], "1h")
        self.assertIn("Actions possibles", bundle.system[0]["text"])
        self.assertIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertIn("Tempo", bundle.prompt)
        self.assertNotIn("Actions possibles", bundle.prompt)
        self.assertEqual(bundle.history_messages_used, 2)


if __name__ == "__main__":
    unittest.main()
