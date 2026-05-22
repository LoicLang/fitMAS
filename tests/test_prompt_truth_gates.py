from __future__ import annotations

import unittest

from fitmas.llm.prompts.conversation_policy import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_conversation_prompt_bundle, build_layered_conversation_prompt
from fitmas.tools.routing import IntentCategory


class PromptTruthGatesTest(unittest.TestCase):
    def test_default_prompt_policy_never_requests_legacy_plan_summary(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
        self.assertFalse(policy.include_plan_summary)

        fallback = select_conversation_prompt_policy(routing_reason="unknown")
        self.assertFalse(fallback.include_plan_summary)

    def test_prompt_bundle_does_not_render_legacy_plan_anchor(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_NEGOTIATION)

        bundle = build_conversation_prompt_bundle(
            user_text="Qu'est-ce qu'il me reste cette semaine ?",
            prompt_policy=policy,
            time_block="Contexte temporel exact.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy weekly plan should never leak.",
            timeline_summary="- id=12 | date=2026-04-10 | [swimming] Natation technique",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Demain = 2026-04-11.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context={"coach_name": "FitMAS"},
            selected_facts=[],
        )

        self.assertNotIn("Repere legacy semaine courante", bundle.prompt)
        self.assertNotIn("Legacy weekly plan should never leak", bundle.prompt)

    def test_layered_prompt_does_not_render_legacy_plan_layer(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.GENERIC_QUESTION)

        bundle = build_layered_conversation_prompt(
            user_text="Aujourd'hui c'est quoi ?",
            prompt_policy=policy,
            time_block="Contexte temporel exact.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy weekly plan should never leak.",
            timeline_summary="- id=14 | date=2026-04-10 | [running] Footing",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Aujourd'hui = 2026-04-10.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context={"coach_name": "FitMAS"},
            selected_facts=[],
        )

        self.assertFalse(any("Repere legacy semaine courante" in part["text"] for part in bundle.system))
        self.assertFalse(any("Legacy weekly plan should never leak" in part["text"] for part in bundle.system))

    def test_classic_generic_prompt_does_not_render_planning_truth_banner(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.GENERIC_QUESTION)

        bundle = build_conversation_prompt_bundle(
            user_text="100 kg, on fait quoi ?",
            prompt_policy=policy,
            time_block="Contexte temporel exact.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy weekly plan should never leak.",
            timeline_summary="- id=14 | date=2026-04-10 | [running] Footing",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Aujourd'hui = 2026-04-10.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context={"coach_name": "FitMAS"},
            selected_facts=[],
        )

        self.assertNotIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertNotIn("Calendrier date reel", bundle.prompt)
        self.assertNotIn("Execution: planned_pending", bundle.prompt)


if __name__ == "__main__":
    unittest.main()
