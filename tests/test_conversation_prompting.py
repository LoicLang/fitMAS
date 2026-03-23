from __future__ import annotations

import unittest

from fitmas.conversation_prompting import select_conversation_prompt_policy


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


if __name__ == "__main__":
    unittest.main()
