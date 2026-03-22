from __future__ import annotations

import unittest
from datetime import datetime

from fitmas.tool_contract import ToolCall, ToolContext
from fitmas.tool_registry import build_tool_registry, list_tools_for_pipeline
from fitmas.tool_runtime import execute_tool_call


class ToolRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T07:00:00+01:00",
                    "sport_type": "swimming",
                    "session_title": "Natation",
                    "duration_min": 60,
                    "completion_status": "planned",
                },
                {
                    "id": 13,
                    "scheduled_date": "2026-03-24T07:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing",
                    "duration_min": 45,
                    "completion_status": "planned",
                },
            ],
            activities=[
                {
                    "id": 33,
                    "started_at": "2026-03-21T18:00:00+01:00",
                    "sport_type": "running",
                    "title": "Footing long",
                    "duration_min": 70,
                    "distance_m": 14000,
                    "avg_speed": 3.3,
                },
                {
                    "id": 34,
                    "started_at": "2026-03-20T18:00:00+01:00",
                    "sport_type": "cycling",
                    "title": "Velo",
                    "duration_min": 90,
                    "distance_m": 36000,
                    "avg_speed": 8.2,
                },
            ],
            active_facts=[
                {
                    "category": "goal",
                    "key": "running_focus",
                    "value": "Retrouver mon niveau running",
                    "source": "conversation",
                    "confidence": 0.9,
                    "confirmed": True,
                    "active": True,
                }
            ],
        )

    def test_registry_exposes_conversation_tools(self) -> None:
        names = {tool["name"] for tool in list_tools_for_pipeline("conversation")}

        self.assertIn("get_today_context", names)
        self.assertIn("get_recent_activities", names)
        self.assertIn("get_relevant_facts", names)

    def test_execute_tool_call_returns_today_context(self) -> None:
        result, trace = execute_tool_call(
            ToolCall(tool_name="get_today_context"),
            context=self.context,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["planned_sport"], "swimming")
        self.assertEqual(trace.tool_name, "get_today_context")
        self.assertTrue(trace.tool_success)
        self.assertTrue(trace.tool_called)

    def test_execute_tool_call_rejects_unknown_tool(self) -> None:
        result, trace = execute_tool_call(
            ToolCall(tool_name="unknown_tool"),
            context=self.context,
        )

        self.assertEqual(result.status, "error")
        self.assertIn("Unknown tool", result.error)
        self.assertFalse(trace.tool_called)
        self.assertFalse(trace.tool_success)

    def test_execute_tool_call_rejects_wrong_pipeline(self) -> None:
        planning_only_context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
        )
        result, trace = execute_tool_call(
            ToolCall(tool_name="get_today_context"),
            context=planning_only_context,
        )

        self.assertEqual(result.status, "error")
        self.assertIn("not allowed", result.error)
        self.assertFalse(trace.tool_called)

    def test_activity_highlights_returns_best_efforts(self) -> None:
        registry = build_tool_registry()
        result = registry["get_activity_highlights"].handler(self.context, {"days": 14})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["longest_duration"]["title"], "Velo")
        self.assertEqual(result.payload["longest_distance"]["title"], "Velo")
        self.assertEqual(result.payload["fastest"]["title"], "Velo")


if __name__ == "__main__":
    unittest.main()
