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
        original_log_tool_trace = llm.log_tool_trace
        captured: dict[str, object] = {"calls": 0}
        traces: list[object] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            captured["calls"] = int(captured["calls"]) + 1
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            if captured["calls"] == 1:
                self.assertIsNotNone(tools)
                self.assertEqual([tool["name"] for tool in tools], ["get_activity_highlights", "get_recent_activities"])
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
                SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=12),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_call = fake_execute_tool_call
        llm.log_tool_trace = lambda trace: traces.append(trace)
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
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertIn("plus longue sortie", decision.fitmas_message.lower())
        self.assertEqual(len(traces), 1)
        self.assertTrue(traces[0].tool_offered)
        self.assertTrue(traces[0].tool_requested)
        self.assertTrue(traces[0].tool_called)
        self.assertEqual(traces[0].tool_name, "get_activity_highlights")
        self.assertEqual(traces[0].llm_round_trips, 2)
        self.assertEqual(traces[0].context_policy, "activity_highlights_compact")
        self.assertEqual(traces[0].tool_count_offered, 2)
        self.assertGreaterEqual(traces[0].prompt_char_count, 1)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertNotIn("Calendrier date reel", prompts[0])

    def test_decide_logs_when_tools_are_offered_but_not_used(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual(
                [tool["name"] for tool in tools],
                ["get_today_context", "get_plan_window", "get_user_constraints"],
            )
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"reponse directe","fitmas_message":"Tu as une sortie running jeudi."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=90, output_tokens=28),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "Jeudi c'est quoi deja ?",
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
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertEqual(len(traces), 1)
        self.assertTrue(traces[0].tool_offered)
        self.assertFalse(traces[0].tool_requested)
        self.assertFalse(traces[0].tool_called)
        self.assertEqual(traces[0].response_stop_reason, "end_turn")
        self.assertFalse(traces[0].fallback_used)
        self.assertEqual(traces[0].context_policy, "plan_lookup_compact")
        self.assertEqual(traces[0].tool_count_offered, 3)
        self.assertGreaterEqual(traces[0].prompt_char_count, 1)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertIn("Source de vérité planning conversationnelle", prompts[0])

    def test_decide_default_prompt_does_not_anchor_on_legacy_week_plan(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"ok","fitmas_message":"Je me cale sur le calendrier daté."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=90, output_tokens=28),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        try:
            decision = llm.decide(
                "C'est pas ce qui est sur mon planning dans l'app",
                "Legacy semaine: footing lundi",
                timeline_summary="- id=12 | date=2026-03-23 | [swimming] Natation app truth | status=planned",
            )
        finally:
            llm._client = original_client
            llm._request_message = original_request_message

        self.assertIsNotNone(decision)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertIn("Source de vérité planning conversationnelle", prompts[0])
        self.assertIn("Natation app truth", prompts[0])

    def test_decide_offers_plan_tools_for_app_plan_dispute(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual(
                [tool["name"] for tool in tools],
                ["get_today_context", "get_plan_window", "get_user_constraints"],
            )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"app truth","fitmas_message":"Je repars du calendrier daté de l app."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=110, output_tokens=30),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "C'est pas ce qui est sur mon planning dans l'app",
                "Legacy semaine: footing lundi",
                timeline_summary="- id=12 | date=2026-03-23 | [swimming] Natation app truth | status=planned",
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
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertEqual(len(traces), 1)
        self.assertTrue(traces[0].tool_offered)
        self.assertEqual(traces[0].context_policy, "plan_lookup_compact")
        self.assertEqual(traces[0].tool_count_offered, 3)

    def test_turn_plan_intent_overrides_keyword_tool_routing(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        prompts: list[str] = []
        systems: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual(
                [tool["name"] for tool in tools],
                ["get_today_context", "get_plan_window", "get_load_context", "get_user_constraints", "propose_replan", "get_relevant_facts"],
            )
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            systems.append("\n".join(part["text"] for part in system) if isinstance(system, list) else str(system))
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"contrainte disponibilite","fitmas_message":"Je vois les seances touchees."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=160, output_tokens=36),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "Cette semaine je voyage de mercredi a vendredi",
                "Repere",
                temporal_summary="Contexte orchestration planning: sessions touchees",
                coach_context={
                    "turn_primary_intent": "availability_constraint",
                    "turn_secondary_intents": [],
                },
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
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertEqual(traces[0].context_policy, "plan_negotiation_full")
        self.assertIn("Contexte orchestration planning", systems[0])

if __name__ == "__main__":
    unittest.main()
