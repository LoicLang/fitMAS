from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.llm import make_timeline_summary
from fitmas.llm_prompt_builder import build_conversation_prompt_bundle, build_layered_conversation_prompt


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
        self.assertIn("Tu varies l'attaque de tes messages", bundle.system[0]["text"])
        self.assertIn("Tu n'ouvres pas systematiquement par \"Bon\", \"OK\", \"Attends\" ou \"On va etre honnete\"", bundle.system[0]["text"])
        self.assertIn("move_session = deplacer une seule seance vers un slot libre", bundle.system[0]["text"])
        self.assertIn("Je veux le renfo aujourd'hui et la piscine demain", bundle.system[0]["text"])
        self.assertIn("On peut echanger mercredi et jeudi ?", bundle.system[0]["text"])
        self.assertIn("swap_sessions", bundle.system[0]["text"])
        self.assertIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertIn("Tempo", bundle.prompt)
        self.assertNotIn("Actions possibles", bundle.prompt)
        self.assertEqual(bundle.history_messages_used, 2)

    def test_layered_builder_splits_system_layers_and_keeps_profile(self) -> None:
        bundle = build_layered_conversation_prompt(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=2, include_plan_summary=False),
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km. Mardi fragile.",
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

        self.assertGreater(len(bundle.system), 1)
        self.assertIn("Actions possibles", bundle.system[0]["text"])
        self.assertIn("Tu varies l'attaque de tes messages", bundle.system[0]["text"])
        self.assertTrue(any("Profil resume" in part["text"] for part in bundle.system))
        self.assertTrue(any("Calendrier date reel" in part["text"] for part in bundle.system))
        self.assertIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertTrue(bundle.prompt.endswith("Nouveau message de l'utilisateur:\nJeudi c'est quoi deja ?"))
        self.assertEqual(bundle.history_messages_used, 2)

    def test_live_prompt_builders_ignore_legacy_plan_anchor_even_if_requested(self) -> None:
        policy = ConversationPromptPolicy(name="forced_legacy", history_limit=2, include_plan_summary=True)

        classic = build_conversation_prompt_bundle(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=policy,
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy plan should never leak.",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )
        layered = build_layered_conversation_prompt(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=policy,
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy plan should never leak.",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )

        classic_system = "\n".join(part["text"] for part in classic.system)
        layered_system = "\n".join(part["text"] for part in layered.system)
        self.assertNotIn("Repere legacy semaine courante", classic.prompt)
        self.assertNotIn("Repere legacy semaine courante", classic_system)
        self.assertNotIn("Legacy plan should never leak.", classic.prompt)
        self.assertNotIn("Legacy plan should never leak.", classic_system)
        self.assertNotIn("Repere legacy semaine courante", layered.prompt)
        self.assertNotIn("Repere legacy semaine courante", layered_system)
        self.assertNotIn("Legacy plan should never leak.", layered.prompt)
        self.assertNotIn("Legacy plan should never leak.", layered_system)

    def test_timeline_summary_marks_training_and_flexible_targets(self) -> None:
        summary = make_timeline_summary(
            [
                SimpleNamespace(
                    id=23,
                    scheduled_date="2026-04-14",
                    day="tuesday",
                    sport_type="strength",
                    session_type="general",
                    session_title="Renfo general",
                    session_goal="Socle",
                    completion_status="planned",
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=26,
                    scheduled_date="2026-04-17",
                    day="friday",
                    sport_type="rest",
                    session_type="rest",
                    session_title="Journee flexible",
                    session_goal="Repos",
                    completion_status="planned",
                    flexibility="flexible",
                ),
            ]
        )

        self.assertIn("id=23 | date=2026-04-14 | day=tuesday | slot=training", summary)
        self.assertIn("swappable=true", summary)
        self.assertIn("movable_target=false", summary)
        self.assertIn("id=26 | date=2026-04-17 | day=friday | slot=free_flexible", summary)
        self.assertIn("movable_target=true", summary)


if __name__ == "__main__":
    unittest.main()
