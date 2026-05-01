from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

import fitmas.llm as llm
from fitmas import llm_gateway as gw
from fitmas.tool_contract import ToolContext, ToolResult


CANONICAL_CONVERSATION_TOOLS = [
    "get_today_context",
    "get_plan_window",
    "resolve_planning_window",
    "get_recent_activities",
    "get_activity_highlights",
    "get_recent_reality_window",
    "get_load_context",
    "get_relevant_facts",
    "get_user_constraints",
    "suggest_replan_candidates",
]


class LLMToolsTest(unittest.TestCase):
    def test_parse_coach_decision_accepts_plan_patch(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "plan_patch",
                "rationale": "piscine fermee, on garde du volume facile",
                "fitmas_message": "Je pose un footing easy mercredi.",
                "plan_patch": {
                    "coach_message": "Je pose un footing easy mercredi.",
                    "operations": [
                        {
                            "operation_type": "create_session",
                            "target_date": "2099-04-29",
                            "new_sport_type": "running",
                            "new_session_type": "easy",
                            "new_title": "Footing easy",
                            "new_duration_min": 30,
                            "rationale": "Remplacement conservateur sans piscine.",
                        }
                    ],
                },
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.response_type, "plan_patch")
        self.assertIsNotNone(decision.plan_patch)
        self.assertEqual(decision.plan_patch.operations[0].operation_type, "create_session")

    def test_parse_coach_decision_rejects_plan_patch_without_patch(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "plan_patch",
                "rationale": "action annoncee sans patch",
                "fitmas_message": "Je modifie le plan.",
            }
        )

        self.assertIsNone(decision)

    def test_parse_coach_decision_rejects_third_person_coach_voice(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "voix indirecte invalide",
                "fitmas_message": "Le coach te demande de choisir entre natation technique et natation CSS.",
            }
        )

        self.assertIsNone(decision)

    def test_parse_coach_decision_accepts_legacy_mutation_decision(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "mutation_decision",
                "rationale": "legacy pendant transition",
                "fitmas_message": "On allege.",
                "mutation_decision": {
                    "mutation_type": "lighten_day",
                    "target_session_id": 42,
                    "rationale": "fatigue signalee",
                    "fitmas_message": "On allege.",
                },
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.response_type, "mutation_decision")
        self.assertIsNotNone(decision.mutation_decision)
        self.assertEqual(decision.mutation_decision.mutation_type, "lighten_day")

    def test_parse_coach_decision_reuses_top_level_rationale_for_nested_mutation(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "mutation_decision",
                "rationale": "continuation courte, creation running mercredi",
                "fitmas_message": "Je pose un footing easy mercredi.",
                "mutation_decision": {
                    "mutation_type": "create_session",
                    "target_date": "2099-04-29",
                    "new_sport_type": "running",
                    "new_session_type": "easy",
                    "new_title": "Footing easy",
                    "new_duration_min": 30,
                    "fitmas_message": "Je pose un footing easy mercredi.",
                },
            }
        )

        self.assertIsNotNone(decision)
        self.assertIsNotNone(decision.mutation_decision)
        self.assertEqual(decision.mutation_decision.rationale, "continuation courte, creation running mercredi")

    def test_parse_coach_decision_defaults_missing_action_confidence(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "execution manquee sans mutation planning",
                "fitmas_message": "Note. Le renfo d'hier n'est pas fait; ce matin on garde le footing facile.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "sport_type": "strength",
                        "evidence": "J'ai pas eu le temps hier",
                    }
                ],
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertGreater(decision.execution_actions[0].confidence, 0)

    def test_parse_coach_decision_drops_malformed_memory_but_keeps_execution_action(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "execution manquee sans mutation planning",
                "fitmas_message": "Note. Le renfo d'hier n'est pas fait; ce matin on garde le footing facile.",
                "memory_actions": [
                    {
                        "type": "record_health_signal",
                        "source": {"kind": "message utilisateur"},
                    }
                ],
                "execution_actions": [
                    {
                        "operation_type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "skipped",
                        "completed": False,
                        "sport_type": "strength",
                        "evidence": "J'ai pas eu le temps hier",
                    }
                ],
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(len(decision.memory_actions), 0)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")

    def test_parse_coach_decision_normalizes_string_confidence(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "execution manquee sans mutation planning",
                "fitmas_message": "Note. Le renfo d'hier n'est pas fait; ce matin on garde le footing facile.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": "high",
                    }
                ],
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.execution_actions[0].confidence, 0.85)

    def test_parse_coach_decision_accepts_execution_target_id_without_ref(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "reply",
                "rationale": "execution manquee sans mutation planning",
                "fitmas_message": "Renfo d'hier note non fait.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_session_id": 123,
                        "completed": "false",
                        "confidence": "high",
                    }
                ],
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.execution_actions[0].target_ref, "session_id:123")
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertIs(decision.execution_actions[0].completed, False)

    def test_legacy_create_session_can_reuse_message_as_rationale(self) -> None:
        decision = llm._parse_llm_decision_payload(
            {
                "mutation_type": "create_session",
                "target_date": "2099-04-29",
                "new_sport_type": "running",
                "new_session_type": "easy",
                "new_title": "Footing easy",
                "new_duration_min": 30,
                "fitmas_message": "Je pose un footing easy mercredi.",
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.rationale, "Je pose un footing easy mercredi.")

    def test_legacy_targetless_replace_with_create_fields_becomes_create_session(self) -> None:
        decision = llm._parse_llm_decision_payload(
            {
                "mutation_type": "replace_session",
                "target_date": "2099-04-29",
                "new_sport_type": "running",
                "new_session_type": "easy",
                "new_title": "Footing easy",
                "new_duration_min": 30,
                "rationale": "piscine fermee, course de remplacement",
                "fitmas_message": "Je pose un footing easy mercredi.",
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "create_session")
        self.assertIsNone(decision.target_session_id)

    def test_decide_accepts_coach_decision_plan_patch_payload(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append("\n".join(part["text"] for part in system if isinstance(part, dict) and part.get("text")))
            return {
                "response_type": "plan_patch",
                "rationale": "piscine fermee, remplacement conservateur",
                "fitmas_message": "Je pose un footing easy mercredi.",
                "plan_patch": {
                    "coach_message": "Je pose un footing easy mercredi.",
                    "operations": [
                        {
                            "operation_type": "create_session",
                            "target_date": "2099-04-29",
                            "new_sport_type": "running",
                            "new_session_type": "easy",
                            "new_title": "Footing easy",
                            "new_duration_min": 30,
                            "rationale": "Remplacement sans piscine.",
                        }
                    ],
                },
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("Piscine fermee deux semaines", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.response_type, "plan_patch")
        self.assertIsNotNone(decision.plan_patch)
        self.assertEqual(decision.plan_patch.operations[0].operation_type, "create_session")
        self.assertIn("CoachDecision", prompts[0])
        self.assertIn("memory_actions", prompts[0])
        self.assertIn("execution_actions", prompts[0])
        self.assertIn("pending_resolution", prompts[0])

    def test_decide_can_complete_single_tool_round_trip(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_log_tool_trace = llm.log_tool_trace
        captured: dict[str, object] = {"calls": 0}
        traces: list[object] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            captured["calls"] = int(captured["calls"]) + 1
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            if captured["calls"] == 1:
                self.assertIsNotNone(tools)
                self.assertEqual([tool["name"] for tool in tools], CANONICAL_CONVERSATION_TOOLS)
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

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertEqual(call.tool_name, "get_activity_highlights")
            self.assertEqual(context.pipeline, "conversation")
            return [
                SimpleNamespace(result=
                ToolResult(
                    tool_name="get_activity_highlights",
                    status="ok",
                    payload={"longest_duration": {"title": "Velo", "duration_min": 90}},
                    summary="1 highlight activite disponible.",
                ),
                trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=12))
            ]

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
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
                coach_context={"turn_primary_intent": "plan_lookup"},
            )
        finally:
            llm._client = original_client
            llm._request_message = original_request_message
            llm.execute_tool_calls = original_execute_tool_calls
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
        self.assertEqual(traces[0].context_policy, "plan_lookup_compact")
        self.assertEqual(traces[0].tool_count_offered, len(CANONICAL_CONVERSATION_TOOLS))
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
            self.assertEqual([tool["name"] for tool in tools], CANONICAL_CONVERSATION_TOOLS)
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
                coach_context={"turn_primary_intent": "plan_lookup"},
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
        self.assertEqual(traces[0].tool_count_offered, len(CANONICAL_CONVERSATION_TOOLS))
        self.assertGreaterEqual(traces[0].prompt_char_count, 1)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertIn("Source de vérité planning conversationnelle", prompts[0])

    def test_decide_offers_canonical_conversation_tools_without_intent_budget(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        offered_tool_names: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            offered_tool_names.extend(tool["name"] for tool in (tools or []))
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","rationale":"lecture outillee","fitmas_message":"Je lis le planning avant de trancher."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=120, output_tokens=32),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm._request_structured_json = lambda **kwargs: {
            "mutation_type": "no_change",
            "rationale": "fallback sans tools",
            "fitmas_message": "Fallback.",
        }
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Je ne peux pas demain soir",
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
            llm._request_structured_json = original_request_structured_json
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(
            offered_tool_names,
            CANONICAL_CONVERSATION_TOOLS,
        )
        self.assertNotIn("propose_replan", offered_tool_names)

    def test_tool_followup_satisfies_every_tool_use_block(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_log_tool_trace = llm.log_tool_trace
        calls = {"count": 0}
        followup_tool_results: list[dict[str, object]] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={}),
                        SimpleNamespace(type="tool_use", id="toolu_2", name="get_user_constraints", input={}),
                    ],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            followup_tool_results.extend(messages[-1]["content"])
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"mutation_type":"no_change","rationale":"lecture","fitmas_message":"OK."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            self.assertEqual([call.tool_name for call in calls], ["get_plan_window", "get_user_constraints"])
            return [
                SimpleNamespace(
                    result=ToolResult(tool_name="get_plan_window", status="ok", payload={"sessions": []}, summary="Plan vide."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                ),
                SimpleNamespace(
                    result=ToolResult(tool_name="get_user_constraints", status="ok", payload={"constraints": []}, summary="Contraintes vides."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                ),
            ]

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Je ne peux pas nager",
                "Repere",
                coach_context={"turn_primary_intent": "availability_constraint"},
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
            llm.execute_tool_calls = original_execute_tool_calls
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(
            [item["tool_use_id"] for item in followup_tool_results],
            ["toolu_1", "toolu_2"],
        )
        self.assertFalse(followup_tool_results[1]["is_error"])

    def test_decide_rejects_unknown_mutation_type_and_uses_structured_fallback(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        calls: list[object] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            calls.append((system, messages, model, max_tokens))
            return {
                "mutation_type": "downgrade",
                "rationale": "hors enum",
                "fitmas_message": "On degrade.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide(
                    "Je suis rince",
                    "Repere",
                )
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNone(decision)
        self.assertEqual(len(calls), 2)

    def test_decide_uses_claude_fallback_when_structured_payload_has_invalid_schema(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        fallback_calls: list[object] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "downgrade",
                "rationale": "hors enum",
                "fitmas_message": "On degrade.",
            }

        def fake_gateway_structured_json(**kwargs):
            fallback_calls.append(kwargs)
            return gw.StructuredJSONResult(
                data={
                    "mutation_type": "lighten_day",
                    "target_session_id": 42,
                    "rationale": "fallback schema valide",
                    "fitmas_message": "On allege.",
                },
                provider="claude_anthropic",
                model="claude-haiku-4-5-20251001",
                provider_fallback_used=True,
            )

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.object(llm.gw, "request_structured_json", side_effect=fake_gateway_structured_json):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
                try:
                    decision = llm.decide("Je suis rince", "Repere")
                finally:
                    llm._client = original_client
                    llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "lighten_day")
        self.assertEqual(fallback_calls[0]["provider"], "claude")

    def test_decide_repairs_invalid_deepseek_decision_before_claude_fallback(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        calls: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            calls.append(str(messages[0]["content"]))
            if len(calls) == 1:
                return {
                    "mutation_type": "downgrade",
                    "target_session_id": 42,
                    "rationale": "enum hors contrat",
                    "fitmas_message": "On degrade.",
                }
            return {
                "mutation_type": "lighten_day",
                "target_session_id": 42,
                "rationale": "enum reparee localement",
                "fitmas_message": "On allege.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Je suis rince", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "lighten_day")
        self.assertEqual(len(calls), 2)
        self.assertIn("PAYLOAD_INVALIDE", calls[1])

    def test_decide_rejects_replace_without_target_session(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "replace_session",
                "target_date": "2026-04-22",
                "rationale": "manque session",
                "fitmas_message": "Je remplace mercredi.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Mercredi", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNone(decision)

    def test_decide_repairs_no_change_that_promises_plan_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "contrainte memorisee mais aucune mutation",
                    "fitmas_message": "Ta piscine fermee est enregistree. Le plan sera ajuste en consequence.",
                }
            return {
                "mutation_type": "no_change",
                "rationale": "contrainte comprise sans mutation planning",
                "fitmas_message": "Piscine fermee deux semaines, note. Je dois lire les seances touchees avant de modifier le plan.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Ma piscine est fermee deux semaines", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertNotIn("sera ajuste", decision.fitmas_message)
        self.assertIn("PAYLOAD_INVALIDE", prompts[1])

    def test_decide_repairs_no_change_that_promises_future_plan_build(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "sport choisi mais aucun patch produit",
                    "fitmas_message": "Donne-moi le jour, je construis la seance.",
                }
            return {
                "mutation_type": "no_change",
                "rationale": "sport choisi sans creneau modifiable",
                "fitmas_message": "Running note. Je dois trouver un creneau modifiable avant de toucher au plan.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Running", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertNotIn("construis", decision.fitmas_message)
        self.assertNotIn("vos", decision.fitmas_message.lower())
        self.assertIn("PAYLOAD_INVALIDE", prompts[1])

    def test_decide_repairs_no_change_that_promises_session_creation(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "aucune session existante a modifier",
                    "fitmas_message": "Mercredi pour du running. Confirme et j'ajoute la seance.",
                }
            return {
                "mutation_type": "no_change",
                "rationale": "creation non supportee sans patch",
                "fitmas_message": "Mercredi pour du running, note. Je dois passer par une creation de seance avant de l'appliquer.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Mercredi", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertNotIn("j'ajoute", decision.fitmas_message)
        self.assertIn("PAYLOAD_INVALIDE", prompts[1])

    def test_decide_repairs_invalid_coach_decision_and_preserves_execution_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "requires_confirmation",
                    "fitmas_message": "Je note que le renfo d'hier n'est pas fait. On garde le footing facile ce matin.",
                    "execution_actions": [
                        {
                            "type": "record_execution_update",
                            "target_ref": "seance d'hier",
                            "status": "not_completed",
                            "completed": False,
                            "sport_type": "strength",
                            "confidence": 0.93,
                            "evidence": "J'ai pas eu le temps hier",
                        }
                    ],
                }
            return {
                "response_type": "no_change",
                "rationale": "execution manquee comprise sans mutation planning",
                "fitmas_message": "Note. Le renfo d'hier n'est pas fait; ce matin on garde le footing facile.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "sport_type": "strength",
                        "confidence": 0.93,
                        "evidence": "J'ai pas eu le temps hier",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertIn("CoachDecision", prompts[1])
        self.assertIn("execution_actions", prompts[1])

    def test_decide_repairs_free_requires_confirmation_into_execution_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "requires_confirmation",
                    "rationale": "renfo non fait hier, il faut savoir si footing aujourd'hui ou demain",
                    "fitmas_message": "Tu peux aujourd'hui ou il faut reporter demain ?",
                    "confirmation_reason": "Savoir si tu peux aujourd'hui ou demain.",
                }
            return {
                "response_type": "no_change",
                "rationale": "renfo non fait hier sans mutation planning immediate",
                "fitmas_message": "Renfo d'hier note non fait. On garde le footing en option simple.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": "high",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertIn("requires_confirmation", prompts[1])

    def test_decide_repairs_execution_receipt_without_execution_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "Message information sur la seance d'hier",
                    "fitmas_message": "C'est note pour hier. Ce matin, le footing Z2 t'attend toujours.",
                }
            return {
                "response_type": "no_change",
                "rationale": "execution manquee hier sans mutation planning",
                "fitmas_message": "C'est note pour hier. Le footing Z2 reste au planning ce matin.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.8,
                        "evidence": "C'est note pour hier",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertIn("execution_actions", prompts[1])

    def test_decide_repairs_vu_pour_hier_missing_execution_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "Utilisateur signale avoir manque la seance d'hier pour raison pro. Pas de demande de modification du plan.",
                    "fitmas_message": "Vu pour hier. Comment tu te sens ce matin pour le footing Z2 28min ?",
                }
            return {
                "response_type": "no_change",
                "rationale": "execution manquee hier sans mutation planning",
                "fitmas_message": "Hier saute, compris. Le footing Z2 reste au planning ce matin.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.85,
                        "evidence": "seance d'hier manquee",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertIn("execution_actions", prompts[1])

    def test_decide_rejects_legacy_no_change_execution_receipt(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "Seance de mercredi non realisee, mais plan inchange pour aujourd'hui",
                    "fitmas_message": "Vu pour hier, le travail avant tout. On garde le footing Z2 ce matin comme prevu, 28min.",
                }
            return {
                "response_type": "no_change",
                "rationale": "execution manquee hier sans mutation planning",
                "fitmas_message": "Hier saute, compris. Le footing Z2 reste au planning ce matin.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.85,
                        "evidence": "seance d'hier non realisee",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertIn("execution_actions", prompts[1])

    def test_decide_rejects_legacy_no_change_imprevu_yesterday_receipt(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "Utilisateur signale imprevu pour la seance d'hier seulement.",
                    "fitmas_message": "Pas grave, la vie. Rien a changer pour aujourd'hui.",
                }
            return {
                "response_type": "no_change",
                "rationale": "execution manquee hier sans mutation planning",
                "fitmas_message": "Hier saute, compris. Le footing Z2 reste au planning ce matin.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.85,
                        "evidence": "imprevu pour la seance d'hier",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("J'ai pas eu le temps hier", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertIn("execution_actions", prompts[1])

    def test_decide_rejects_truncated_confirmation_message_and_repairs(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "mutation_type": "no_change",
                    "rationale": "jour compris mais session incertaine",
                    "fitmas_message": "D'accord, mercredi. Par defaut je mets un footing easy. Confirme que c'est bien",
                }
            return {
                "mutation_type": "no_change",
                "rationale": "jour compris mais session incertaine",
                "fitmas_message": "D'accord, mercredi. Je dois savoir quelle seance remplacer avant de toucher au calendrier.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Mercredi", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertNotIn("Confirme que c'est bien", decision.fitmas_message)
        self.assertIn("ne laisse jamais fitmas_message tronque", prompts[1])

    def test_decide_accepts_valid_structured_decision(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "lighten_day",
                "target_session_id": 42,
                "rationale": "fatigue signalee",
                "fitmas_message": "On allege aujourd'hui.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("Je suis rince", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "lighten_day")
        self.assertEqual(decision.target_session_id, 42)

    def test_decide_accepts_valid_create_session_decision(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "create_session",
                "target_date": "2099-04-29",
                "new_sport_type": "running",
                "new_session_type": "easy",
                "new_title": "Footing easy",
                "new_duration_min": 30,
                "new_intensity": "easy",
                "rationale": "remplacement piscine conservateur",
                "fitmas_message": "Je pose un footing easy mercredi.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("Mercredi", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "create_session")
        self.assertEqual(decision.target_date, "2099-04-29")
        self.assertEqual(decision.new_sport_type, "running")

    def test_decide_rejects_create_session_without_required_fields(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "create_session",
                "target_date": "2099-04-29",
                "rationale": "trop vague",
                "fitmas_message": "Je pose une séance.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide("Mercredi", "Repere")
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsNone(decision)

    def test_tool_followup_prose_is_repaired_as_structured_decision(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"count": 0}
        repair_prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(type="tool_use", id="toolu_1", name="get_today_context", input={}),
                    ],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text="Je libere le footing de ce soir. On garde le tempo demain.",
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(tool_name=calls[0].tool_name, status="ok", payload={"today": "footing"}, summary="Footing ce soir."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            repair_prompts.append(str(messages[0]["content"]))
            return {
                "mutation_type": "lighten_day",
                "target_session_id": 42,
                "rationale": "prose reparee",
                "fitmas_message": "Je libere le footing de ce soir.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Je ne peux pas ce soir",
                "Repere",
                coach_context={"turn_primary_intent": "availability_constraint"},
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
            llm.execute_tool_calls = original_execute_tool_calls
            llm._request_structured_json = original_request_structured_json
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "lighten_day")
        self.assertEqual(repair_prompts, [repair_prompts[0]])
        self.assertIn("Je libere le footing", repair_prompts[0])
        self.assertIn("CONTEXTE_ORIGINAL", repair_prompts[0])
        self.assertIn("Je ne peux pas ce soir", repair_prompts[0])
        self.assertIn("execution_actions", repair_prompts[0])

    def test_tool_followup_dsml_tool_markup_is_not_repaired_as_user_message(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"messages": 0, "structured": 0}

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            calls["messages"] += 1
            if calls["messages"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_today_context", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='<｜DSML｜tool_calls><｜DSML｜invoke name="get_activities"></｜DSML｜invoke></｜DSML｜tool_calls>',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(tool_name=calls[0].tool_name, status="ok", payload={"today": "context"}, summary="Contexte."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            calls["structured"] += 1
            return {
                "mutation_type": "no_change",
                "rationale": "fallback structured apres markup provider",
                "fitmas_message": "Je regarde les seances reelles disponibles.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Regarde mes seances reelles",
                "Repere",
                coach_context={"turn_primary_intent": "plan_lookup"},
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
            llm.execute_tool_calls = original_execute_tool_calls
            llm._request_structured_json = original_request_structured_json
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertNotIn("pas reçu", decision.fitmas_message)
        self.assertEqual(calls["structured"], 1)

    def test_deepseek_structured_path_is_default_when_key_exists(self) -> None:
        original_request_message = llm._request_message
        structured_calls: list[dict[str, object]] = []

        def fake_request_message(*args, **kwargs):
            raise AssertionError("DeepSeek structured decisions should not use text JSON path")

        def fake_gateway_structured_json(**kwargs):
            structured_calls.append(kwargs)
            return SimpleNamespace(
                data={
                    "mutation_type": "no_change",
                    "rationale": "continuation courte traitee par JSON mode",
                    "fitmas_message": "Je garde le cap.",
                },
                provider="deepseek_openai",
                model="deepseek-v4-flash",
                error=None,
                provider_fallback_used=False,
            )

        llm._request_message = fake_request_message
        with patch.object(llm.gw, "request_structured_json", side_effect=fake_gateway_structured_json):
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                try:
                    data = llm._request_structured_json(
                        system="system",
                        messages=[{"role": "user", "content": "Oui"}],
                    )
                finally:
                    llm._request_message = original_request_message

        self.assertEqual(data["mutation_type"], "no_change")
        self.assertEqual(len(structured_calls), 1)

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
            self.assertEqual([tool["name"] for tool in tools], CANONICAL_CONVERSATION_TOOLS)
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
                coach_context={"turn_primary_intent": "plan_lookup"},
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
        self.assertEqual(traces[0].tool_count_offered, len(CANONICAL_CONVERSATION_TOOLS))

    def test_turn_plan_intent_does_not_narrow_canonical_tool_budget(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        prompts: list[str] = []
        systems: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual([tool["name"] for tool in tools], CANONICAL_CONVERSATION_TOOLS)
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
