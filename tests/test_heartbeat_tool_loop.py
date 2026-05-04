from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

import fitmas.heartbeat as heartbeat
from fitmas.skills.heartbeat import tool_loop
from fitmas.tool_contract import ToolContext


class HeartbeatToolLoopTest(unittest.TestCase):
    def test_llm_generate_executes_heartbeat_read_tool_before_final_reply(self) -> None:
        requests: list[dict] = []
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="get_plan_window",
                        input={"start_date": "2026-05-04", "end_date": "2026-05-05"},
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Je garde juste un oeil: demain reste leger.")],
            ),
        ]

        def fake_request_message(**kwargs):
            requests.append(kwargs)
            return responses.pop(0)

        context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T07:30:00+02:00"),
            scheduled_sessions=[
                {
                    "id": 10,
                    "scheduled_date": "2026-05-05T07:00:00+02:00",
                    "sport_type": "running",
                    "session_title": "Footing facile",
                    "duration_min": 35,
                    "completion_status": "planned",
                }
            ],
        )

        original_request_message = tool_loop.gw.request_message
        original_request_text = heartbeat.request_text
        try:
            tool_loop.gw.request_message = fake_request_message
            heartbeat.request_text = lambda **_kwargs: "ALLOW"
            with heartbeat.capture_debug_trace("morning") as trace:
                text = heartbeat._llm_generate(
                    "system",
                    "prompt",
                    pipeline="heartbeat_briefing",
                    tool_context=context,
                )
        finally:
            tool_loop.gw.request_message = original_request_message
            heartbeat.request_text = original_request_text

        self.assertEqual(text, "Je garde juste un oeil: demain reste leger.")
        self.assertEqual(len(requests), 2)
        self.assertIn("tools", requests[0])
        self.assertEqual(requests[0]["tool_choice"], {"type": "auto"})
        followup_content = requests[1]["messages"][-1]["content"]
        self.assertEqual(followup_content[0]["type"], "tool_result")
        self.assertEqual(followup_content[0]["tool_use_id"], "toolu_1")
        self.assertIn("Footing facile", followup_content[0]["content"])
        self.assertIn("get_plan_window", trace.tools["offered"])
        self.assertIn("get_recent_activities", trace.tools["offered"])
        self.assertEqual(trace.tools["requested"], ["get_plan_window"])
        self.assertEqual(trace.tools["results"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
