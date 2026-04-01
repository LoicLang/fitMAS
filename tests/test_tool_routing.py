from __future__ import annotations

import unittest

from fitmas.tool_routing import route_tools_for_query


class ToolRoutingTest(unittest.TestCase):
    def test_routes_activity_highlights_queries_to_activity_tools(self) -> None:
        decision = route_tools_for_query("C'etait quoi ma plus longue sortie recente ?", pipeline="conversation")

        self.assertEqual(decision.reason, "activity_highlights")
        self.assertEqual(decision.tool_names, ("get_activity_highlights", "get_recent_activities"))

    def test_routes_plan_queries_to_plan_tools(self) -> None:
        decision = route_tools_for_query("Jeudi c'est quoi deja ?", pipeline="conversation")

        self.assertEqual(decision.reason, "plan_lookup")
        self.assertEqual(decision.tool_names, ("get_today_context", "get_plan_window"))

    def test_routes_plan_dispute_queries_to_plan_tools(self) -> None:
        decision = route_tools_for_query("C'est pas ce qui est sur mon planning dans l'app", pipeline="conversation")

        self.assertEqual(decision.reason, "plan_dispute")
        self.assertEqual(decision.tool_names, ("get_today_context", "get_plan_window"))

    def test_routes_load_questions_to_load_tools(self) -> None:
        decision = route_tools_for_query("La charge de cette semaine elle dit quoi ?", pipeline="conversation")

        self.assertEqual(decision.reason, "load_context")
        self.assertEqual(decision.tool_names, ("get_load_context", "get_recent_reality_window"))

    def test_routes_fact_queries_to_memory_tool(self) -> None:
        decision = route_tools_for_query("Qu'est-ce que tu sais de mes contraintes ?", pipeline="conversation")

        self.assertEqual(decision.reason, "fact_recall")
        self.assertEqual(decision.tool_names, ("get_relevant_facts",))

    def test_does_not_offer_tools_for_simple_feedback(self) -> None:
        decision = route_tools_for_query("Ok merci coach", pipeline="conversation")

        self.assertEqual(decision.reason, "no_tool_needed")
        self.assertEqual(decision.tool_names, ())


if __name__ == "__main__":
    unittest.main()
