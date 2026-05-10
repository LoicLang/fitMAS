from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas import conversation_pipeline
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.tools.routing import IntentCategory


class ConversationPromptingTest(unittest.TestCase):
    def test_activity_highlights_policy_is_compact(self) -> None:
        policy = select_conversation_prompt_policy(routing_reason="activity_highlights")

        self.assertEqual(policy.name, "activity_highlights_compact")
        self.assertFalse(policy.include_plan_summary)
        self.assertFalse(policy.include_timeline)
        self.assertFalse(policy.include_execution)
        self.assertEqual(policy.history_limit, 2)

    def test_plan_lookup_policy_keeps_schedule_context(self) -> None:
        policy = select_conversation_prompt_policy(routing_reason="plan_lookup")

        self.assertEqual(policy.name, "plan_lookup_compact")
        self.assertFalse(policy.include_plan_summary)
        self.assertTrue(policy.include_timeline)
        self.assertTrue(policy.include_execution)
        self.assertFalse(policy.include_signals)

    def test_default_policy_stays_full(self) -> None:
        policy = select_conversation_prompt_policy(routing_reason=None)

        self.assertEqual(policy.name, "default_full")
        self.assertFalse(policy.include_plan_summary)
        self.assertTrue(policy.include_signals)
        self.assertEqual(policy.history_limit, 8)

    def test_intent_based_lookup_preferred(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_NEGOTIATION)

        self.assertEqual(policy.name, "plan_negotiation_full")
        self.assertTrue(policy.include_signals)
        self.assertTrue(policy.include_facts)
        self.assertEqual(policy.history_limit, 6)

    def test_casual_chat_is_compact(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.CASUAL_CHAT)

        self.assertEqual(policy.name, "casual_compact")
        self.assertFalse(policy.include_timeline)
        self.assertFalse(policy.include_signals)
        self.assertFalse(policy.include_coach_context)
        self.assertFalse(policy.include_open_question_marker)

    def test_close_turn_uses_terminal_policy(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.CLOSE_TURN)

        self.assertEqual(policy.name, "casual_close")
        self.assertEqual(policy.history_limit, 3)
        self.assertFalse(policy.include_timeline)
        self.assertFalse(policy.include_execution)
        self.assertFalse(policy.include_claim)
        self.assertFalse(policy.include_signals)
        self.assertFalse(policy.include_facts)
        self.assertFalse(policy.include_coach_context)
        self.assertFalse(policy.include_open_question_marker)

    def test_intent_takes_precedence_over_routing_reason(self) -> None:
        policy = select_conversation_prompt_policy(
            routing_reason="fact_recall",
            intent=IntentCategory.LOAD_REVIEW,
        )
        self.assertEqual(policy.name, "load_review")

    def test_clarification_and_calibration_intents_never_use_default_full(self) -> None:
        clarification_policy = select_conversation_prompt_policy(intent=IntentCategory.NEEDS_CLARIFICATION)
        calibration_policy = select_conversation_prompt_policy(intent=IntentCategory.CALIBRATION_ANSWER)

        self.assertNotEqual(clarification_policy.name, "default_full")
        self.assertEqual(clarification_policy.contract_name, "conversation_needs_clarification")
        self.assertFalse(clarification_policy.include_signals)
        self.assertFalse(clarification_policy.include_facts)

        self.assertNotEqual(calibration_policy.name, "default_full")
        self.assertEqual(calibration_policy.contract_name, "conversation_calibration_answer")
        self.assertFalse(calibration_policy.include_signals)
        self.assertFalse(calibration_policy.include_facts)

    def test_generic_question_uses_general_context_without_planning_by_default(self) -> None:
        policy = select_conversation_prompt_policy(intent=IntentCategory.GENERIC_QUESTION)

        self.assertEqual(policy.name, "generic_question_compact")
        self.assertEqual(policy.contract_name, "conversation_generic_question")
        self.assertFalse(policy.include_timeline)
        self.assertFalse(policy.include_execution)
        self.assertFalse(policy.include_claim)
        self.assertTrue(policy.include_facts)
        self.assertFalse(policy.include_coach_context)
        self.assertFalse(policy.include_open_question_marker)

    def test_read_only_policies_do_not_carry_thread_pressure_or_coach_digest(self) -> None:
        for intent in (
            IntentCategory.PLAN_LOOKUP,
            IntentCategory.ACTIVITY_REVIEW,
            IntentCategory.ACTIVITY_HIGHLIGHTS,
            IntentCategory.LOAD_REVIEW,
            IntentCategory.FACT_RECALL,
        ):
            with self.subTest(intent=intent):
                policy = select_conversation_prompt_policy(intent=intent)

                self.assertFalse(policy.include_coach_context)
                self.assertFalse(policy.include_open_question_marker)

    def test_plan_lookup_does_not_build_coach_reading_digest(self) -> None:
        called = False

        def fake_build_digest(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("plan_lookup should not build coach reading digest")

        original = conversation_pipeline.build_coach_reading_digest
        try:
            conversation_pipeline.build_coach_reading_digest = fake_build_digest
            digest = conversation_pipeline._maybe_build_coach_reading_digest_text(
                None,
                user=None,
                today=None,
                recent_reality_window=None,
                turn_plan=SimpleNamespace(primary_intent="plan_lookup"),
            )
        finally:
            conversation_pipeline.build_coach_reading_digest = original

        self.assertIsNone(digest)
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
