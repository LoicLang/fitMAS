from __future__ import annotations

import unittest
from types import SimpleNamespace

import fitmas.llm as llm
from fitmas.tool_contract import ToolContext, ToolResult


class LLMToolsTest(unittest.TestCase):
    def test_decide_can_complete_single_tool_round_trip(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_call = llm.execute_tool_call
        captured: dict[str, object] = {"calls": 0}

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            captured["calls"] = int(captured["calls"]) + 1
            if captured["calls"] == 1:
                self.assertIsNotNone(tools)
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="toolu_123",
                            name="get_activity_highlights",
                            input={"days": 30},
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            self.assertEqual(messages[-1]["content"][0]["type"], "tool_result")
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"lecture outillee","fitmas_message":"Ta plus longue sortie recente est Velo."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_call(call, *, context, **kwargs):
            self.assertEqual(call.tool_name, "get_activity_highlights")
            self.assertEqual(context.pipeline, "conversation")
            return (
                ToolResult(
                    tool_name="get_activity_highlights",
                    status="ok",
                    payload={"longest_duration": {"title": "Velo", "duration_min": 90}},
                    summary="1 highlight activite disponible.",
                ),
                SimpleNamespace(tool_success=True),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_call = fake_execute_tool_call
        try:
            decision = llm.decide(
                "C'etait quoi ma plus longue sortie recente ?",
                "Repere",
                tool_context=ToolContext(
                    pipeline="conversation",
                    user_id=1,
                    timezone_name="Europe/Paris",
                    scheduled_sessions=[],
                    activities=[],
                    active_facts=[],
                ),
            )
        finally:
            llm._client = original_client
            llm._request_message = original_request_message
            llm.execute_tool_call = original_execute_tool_call

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertIn("plus longue sortie", decision.fitmas_message.lower())


if __name__ == "__main__":
    unittest.main()
