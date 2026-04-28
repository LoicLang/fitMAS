from __future__ import annotations

import unittest

from fitmas.tool_routing import IntentCategory, classify_intent, route_tools_for_query


class ToolRoutingTest(unittest.TestCase):
    def test_routes_activity_highlights_queries_to_activity_tools(self) -> None:
        decision = route_tools_for_query("C'etait quoi ma plus longue sortie recente ?", pipeline="conversation")

        self.assertEqual(decision.reason, "activity_highlights")
        self.assertEqual(decision.tool_names, ("get_activity_highlights", "get_recent_activities"))

    def test_routes_plan_queries_to_plan_tools(self) -> None:
        decision = route_tools_for_query("Jeudi c'est quoi deja ?", pipeline="conversation")

        self.assertEqual(decision.reason, "plan_lookup")
        self.assertEqual(
            decision.tool_names,
            ("get_today_context", "get_plan_window", "get_user_constraints"),
        )

    def test_routes_plan_negotiation_to_candidate_replan_helper(self) -> None:
        decision = route_tools_for_query("Je ne peux pas nager pendant deux semaines", pipeline="conversation")

        self.assertEqual(decision.intent, IntentCategory.PLAN_NEGOTIATION)
        self.assertIn("suggest_replan_candidates", decision.tool_names)
        self.assertNotIn("propose_replan", decision.tool_names)

    def test_routes_plan_dispute_queries_to_plan_tools(self) -> None:
        decision = route_tools_for_query("C'est pas ce qui est sur mon planning dans l'app", pipeline="conversation")

        self.assertEqual(decision.reason, "plan_lookup")
        self.assertEqual(
            decision.tool_names,
            ("get_today_context", "get_plan_window", "get_user_constraints"),
        )

    def test_routes_load_questions_to_load_tools(self) -> None:
        decision = route_tools_for_query("La charge de cette semaine elle dit quoi ?", pipeline="conversation")

        self.assertEqual(decision.reason, "load_review")
        self.assertEqual(decision.tool_names, ("get_load_context", "get_recent_reality_window"))

    def test_routes_fact_queries_to_memory_tool(self) -> None:
        decision = route_tools_for_query("Qu'est-ce que tu sais de mes contraintes ?", pipeline="conversation")

        self.assertEqual(decision.reason, "fact_recall")
        self.assertEqual(decision.tool_names, ("get_relevant_facts",))

    def test_does_not_offer_tools_for_simple_feedback(self) -> None:
        decision = route_tools_for_query("Ok merci coach", pipeline="conversation")

        self.assertEqual(decision.reason, "casual_chat")
        self.assertEqual(decision.tool_names, ())

    def test_unsupported_pipeline_returns_empty(self) -> None:
        decision = route_tools_for_query("test", pipeline="unknown")

        self.assertEqual(decision.reason, "unsupported_pipeline")
        self.assertEqual(decision.tool_names, ())


class IntentClassificationTest(unittest.TestCase):
    def test_execution_report(self) -> None:
        self.assertEqual(classify_intent("J'ai fait ma seance ce matin"), IntentCategory.EXECUTION_REPORT)

    def test_plan_negotiation(self) -> None:
        self.assertEqual(classify_intent("Je bascule la seance sur jeudi"), IntentCategory.PLAN_NEGOTIATION)

    def test_casual_chat_default(self) -> None:
        self.assertEqual(classify_intent("Salut"), IntentCategory.CASUAL_CHAT)

    def test_activity_review(self) -> None:
        self.assertEqual(classify_intent("J'ai fait quoi cette semaine ?"), IntentCategory.ACTIVITY_REVIEW)

    def test_load_review(self) -> None:
        self.assertEqual(classify_intent("C'est quoi ma charge cette semaine ?"), IntentCategory.LOAD_REVIEW)

    def test_intent_is_on_routing_decision(self) -> None:
        decision = route_tools_for_query("J'ai couru 10 bornes", pipeline="conversation")
        self.assertEqual(decision.intent, IntentCategory.EXECUTION_REPORT)


if __name__ == "__main__":
    unittest.main()
