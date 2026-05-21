from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

import fitmas.llm.decision_legacy as llm
import fitmas.llm.gateway as gw
from fitmas.tools.contract import ToolContext, ToolResult


CANONICAL_CONVERSATION_TOOLS = [
    "get_plan_window",
    "resolve_planning_window",
    "get_user_constraints",
    "validate_plan_patch",
]

AVAILABILITY_CONSTRAINT_TOOLS = [
    "resolve_planning_window",
    "get_plan_window",
    "get_user_constraints",
]

HEALTH_SIGNAL_TOOLS = [
    "get_plan_window",
    "get_user_constraints",
    "validate_plan_patch",
]

PLAN_LOOKUP_CONTRACT_TOOLS = [
    "get_plan_window",
]


def _system_text(system) -> str:
    if isinstance(system, list):
        return "\n".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in system
        )
    return str(system or "")


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

    def test_parse_coach_decision_preserves_requires_confirmation_plan_patch(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "deplacement sensible",
                "fitmas_message": "Je peux le faire, mais je veux ton feu vert avant de toucher la semaine.",
                "confirmation_reason": "deplacement d'une seance cle",
                "plan_patch": {
                    "coach_message": "Je peux deplacer le tempo a jeudi.",
                    "operations": [
                        {
                            "operation_type": "move_session",
                            "target_session_id": 2,
                            "target_date": "2099-03-24",
                            "rationale": "Indisponibilite lundi soir.",
                        }
                    ],
                },
            }
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.response_type, "requires_confirmation")
        self.assertIsNotNone(decision.plan_patch)
        self.assertEqual(decision.plan_patch.operations[0].target_session_id, 2)

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
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        captured: dict[str, object] = {"calls": 0}
        traces: list[object] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            captured["calls"] = int(captured["calls"]) + 1
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            if captured["calls"] == 1:
                self.assertIsNotNone(tools)
                self.assertEqual([tool["name"] for tool in tools], PLAN_LOOKUP_CONTRACT_TOOLS)
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="toolu_123",
                            name="get_plan_window",
                            input={"window": "current_week"},
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
                        text='{"mutation_type":"no_change","target_session_id":null,"second_session_id":null,"target_date":null,"from_day":null,"to_day":null,"new_title":null,"new_goal":null,"rationale":"lecture outillee","fitmas_message":"Jeudi, tu as une sortie running."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertEqual(call.tool_name, "get_plan_window")
            self.assertEqual(context.pipeline, "conversation")
            return [
                SimpleNamespace(result=
                ToolResult(
                    tool_name="get_plan_window",
                    status="ok",
                    payload={"sessions": [{"title": "Sortie running", "date": "2099-04-29"}]},
                    summary="1 seance planning disponible.",
                ),
                trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=12))
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "no_change",
                "rationale": "lecture outillee compilee",
                "fitmas_message": "Jeudi, tu as une sortie running.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
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
            llm._request_structured_json = original_request_structured_json
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.mutation_type, "no_change")
        self.assertIn("sortie running", decision.fitmas_message.lower())
        self.assertEqual(len(traces), 1)
        self.assertTrue(traces[0].tool_offered)
        self.assertTrue(traces[0].tool_requested)
        self.assertTrue(traces[0].tool_called)
        self.assertEqual(traces[0].tool_name, "get_plan_window")
        self.assertEqual(traces[0].llm_round_trips, 3)
        self.assertEqual(traces[0].context_policy, "plan_lookup_compact")
        self.assertEqual(traces[0].tool_count_offered, len(PLAN_LOOKUP_CONTRACT_TOOLS))
        self.assertGreaterEqual(traces[0].prompt_char_count, 1)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertNotIn("Calendrier date reel", prompts[0])

    def test_tool_followup_json_is_compiled_before_decision_parse(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"messages": 0, "structured": 0}
        compiler_prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            calls["messages"] += 1
            if calls["messages"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"json direct non fiable","fitmas_message":"Message direct de la phase tool."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(
                        tool_name=calls[0].tool_name,
                        status="ok",
                        payload={"sessions": [{"id": 77, "scheduled_date": "2099-04-29", "session_title": "Sortie running"}]},
                        summary="Une seance running trouvee.",
                    ),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            calls["structured"] += 1
            compiler_prompts.append(str(messages[0]["content"]))
            return {
                "response_type": "no_change",
                "rationale": "decision compilee depuis les resultats tools",
                "fitmas_message": "Je vois la sortie running du 29 avril.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Redonne-moi la seance du 29",
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
        self.assertEqual(decision.fitmas_message, "Je vois la sortie running du 29 avril.")
        self.assertEqual(calls["messages"], 2)
        self.assertEqual(calls["structured"], 1)
        self.assertIn("RESULTATS_TOOLS", compiler_prompts[0])
        self.assertIn('"id": 77', compiler_prompts[0])
        self.assertIn("Message direct de la phase tool", compiler_prompts[0])

    def test_tool_compiler_provider_error_falls_back_to_tool_phase_json(self) -> None:
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
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"fallback direct","fitmas_message":"Je garde la reponse de secours."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(
                        tool_name=calls[0].tool_name,
                        status="ok",
                        payload={"sessions": []},
                        summary="Plan lu.",
                    ),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def failing_request_structured_json(*args, **kwargs):
            calls["structured"] += 1
            raise RuntimeError("compiler provider unavailable")

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = failing_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Relis mon plan",
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
        self.assertEqual(decision.fitmas_message, "Je garde la reponse de secours.")
        self.assertEqual(calls["messages"], 2)
        self.assertEqual(calls["structured"], 1)

    def test_decide_logs_when_tools_are_offered_but_not_used(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        prompts: list[str] = []
        system_prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual([tool["name"] for tool in tools], PLAN_LOOKUP_CONTRACT_TOOLS)
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            system_prompts.append(_system_text(system))
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
        self.assertEqual(traces[0].tool_count_offered, len(PLAN_LOOKUP_CONTRACT_TOOLS))
        self.assertGreaterEqual(traces[0].prompt_char_count, 1)
        self.assertNotIn("Repere legacy semaine courante", prompts[0])
        self.assertIn("Source de verite planning conversationnelle", system_prompts[0])

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
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"count": 0}
        followup_tool_results: list[dict[str, object]] = []
        followup_text_blocks: list[str] = []

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
            followup_tool_results.extend(
                item for item in messages[-1]["content"] if item.get("type") == "tool_result"
            )
            followup_text_blocks.extend(
                str(item.get("text") or "") for item in messages[-1]["content"] if item.get("type") == "text"
            )
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

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "mutation_type": "no_change",
                "rationale": "lecture compilee",
                "fitmas_message": "OK.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
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
            llm._request_structured_json = original_request_structured_json
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(
            [item["tool_use_id"] for item in followup_tool_results],
            ["toolu_1", "toolu_2"],
        )
        self.assertFalse(followup_tool_results[1]["is_error"])
        self.assertTrue(any("JSON FitMAS" in text for text in followup_text_blocks))

    def test_tool_loop_allows_second_round_after_results(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"messages": 0}
        executed_batches: list[list[str]] = []
        tool_result_ids_by_round: list[list[str]] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            calls["messages"] += 1
            if calls["messages"] == 1:
                self.assertIsNotNone(tools)
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            if calls["messages"] == 2:
                self.assertIsNotNone(tools)
                tool_result_ids_by_round.append(
                    [item["tool_use_id"] for item in messages[-1]["content"] if item.get("type") == "tool_result"]
                )
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="toolu_2",
                            name="validate_plan_patch",
                            input={
                                "patch": {
                                    "coach_message": "Patch a verifier.",
                                    "operations": [],
                                }
                            },
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=160, output_tokens=36),
                )
            tool_result_ids_by_round.append(
                [item["tool_use_id"] for item in messages[-1]["content"] if item.get("type") == "tool_result"]
            )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"lecture puis validation","fitmas_message":"Je valide avant de toucher au plan."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=190, output_tokens=42),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            executed_batches.append([call.tool_name for call in calls])
            return [
                SimpleNamespace(
                    result=ToolResult(tool_name=call.tool_name, status="ok", payload={}, summary=f"{call.tool_name} ok."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
                for call in calls
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "response_type": "no_change",
                "rationale": "lecture puis validation compilee",
                "fitmas_message": "Je valide avant de toucher au plan.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Je ne peux pas demain, verifie puis adapte",
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
        self.assertEqual(calls["messages"], 3)
        self.assertEqual(executed_batches, [["get_plan_window"], ["validate_plan_patch"]])
        self.assertEqual(tool_result_ids_by_round, [["toolu_1"], ["toolu_2"]])

    def test_tool_loop_can_enable_deepseek_thinking_experiment(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        thinking_calls: list[tuple[object, object]] = []

        def fake_request_message(
            *,
            system,
            messages,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            tools=None,
            tool_choice=None,
            thinking=None,
            output_config=None,
        ):
            thinking_calls.append((thinking, output_config))
            if len(thinking_calls) == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"lecture outillee","fitmas_message":"Je relis avant de toucher au plan."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=180, output_tokens=48),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(tool_name="get_plan_window", status="ok", payload={}, summary="Plan lu."),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "response_type": "no_change",
                "rationale": "lecture outillee compilee",
                "fitmas_message": "Je relis avant de toucher au plan.",
            }

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fake_request_structured_json
        llm.log_tool_trace = lambda trace: None
        try:
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "sk-ds-test",
                    "FITMAS_DEEPSEEK_TOOL_THINKING": "1",
                    "FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT": "max",
                },
                clear=True,
            ):
                decision = llm.decide(
                    "Je ne peux pas demain, relis avant d'adapter",
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
        self.assertEqual(thinking_calls, [({"type": "enabled"}, {"effort": "max"}), ({"type": "enabled"}, {"effort": "max"})])

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

    def test_decide_logs_empty_output_reason_when_provider_returns_no_data(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json

        llm._client = lambda: object()
        llm._request_structured_json = lambda *args, **kwargs: None
        try:
            with self.assertLogs("fitmas.llm", level="INFO") as captured:
                decision = llm.decide(
                    "J'ai quoi demain ?",
                    "Repere",
                    coach_context={"turn_primary_intent": "plan_lookup"},
                )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsNone(decision)
        self.assertTrue(
            any("llm.decide_none reason=empty_output" in record.getMessage() for record in captured.records),
            [record.getMessage() for record in captured.records],
        )

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

    def test_decide_repairs_execution_receipt_after_failed_json_repair_when_followup_target_is_structured(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            return {
                "response_type": "no_change",
                "rationale": "Utilisateur signale un imprevu hier, seance non faite.",
                "fitmas_message": "Vu pour hier. On repart proprement ce matin.",
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        with patch.dict("os.environ", {}, clear=True):
            try:
                decision = llm.decide(
                    "J'ai pas eu le temps hier malheureusement",
                    "Repere",
                    coach_context={
                        "unresolved_execution_followup": "Suivi execution non resolu",
                        "unresolved_execution_followup_session_id": 123,
                        "unresolved_execution_followup_target_date": "2026-05-03",
                    },
                )
            finally:
                llm._client = original_client
                llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].target_session_id, 123)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertIs(decision.execution_actions[0].completed, False)
        self.assertGreaterEqual(len(prompts), 2)

    def test_decide_repairs_execution_action_status_contradicting_reply(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "Course faite aujourd'hui, 30 min.",
                    "fitmas_message": "Vu pour ta course de 30 minutes aujourd'hui, je te la compte.",
                    "execution_actions": [
                        {
                            "type": "record_execution_update",
                            "target_ref": "seance d'aujourd'hui",
                            "target_session_id": 123,
                            "status": "not_completed",
                            "completed": False,
                            "confidence": 0.86,
                        }
                    ],
                }
            return {
                "response_type": "no_change",
                "rationale": "Course faite aujourd'hui, 30 min.",
                "fitmas_message": "Vu pour ta course de 30 minutes aujourd'hui, je te la compte.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'aujourd'hui",
                        "target_session_id": 123,
                        "status": "completed",
                        "completed": True,
                        "duration_min": 30,
                        "confidence": 0.86,
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "J'ai couru aujourd'hui 30 min",
                "Repere",
                coach_context={"verify_execution_actions": True},
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].status, "completed")
        self.assertIs(decision.execution_actions[0].completed, True)
        self.assertIn("execution_actions", prompts[1])

    def test_decide_repairs_valid_followup_reply_missing_execution_action(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "reply",
                    "rationale": "User explique l'absence d'execution hier (renfo id=123).",
                    "fitmas_message": "Compris. Aujourd'hui on garde le footing facile.",
                    "memory_actions": [
                        {
                            "type": "record_availability",
                            "window_text": "imprevu travail hier",
                            "availability": "limited",
                            "confidence": 0.8,
                        }
                    ],
                }
            return {
                "response_type": "reply",
                "rationale": "Execution manquee hier sur le renfo id=123.",
                "fitmas_message": "Compris. Aujourd'hui on garde le footing facile.",
                "memory_actions": [
                    {
                        "type": "record_availability",
                        "window_text": "imprevu travail hier",
                        "availability": "limited",
                        "confidence": 0.8,
                    }
                ],
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "target_session_id": 123,
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.9,
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "J'ai pas eu le temps hier malheureusement",
                "Repere",
                coach_context={
                    "unresolved_execution_followup": "Suivi execution non resolu",
                    "unresolved_execution_followup_session_id": 123,
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].target_session_id, 123)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertIn("Suivi execution non resolu", prompts[1])

    def test_decide_repairs_valid_yesterday_execution_reply_without_followup_id(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "reply",
                    "rationale": "User explique pourquoi le renfo d'hier a saute.",
                    "fitmas_message": "D'accord. Le footing ce matin, tu le sens ?",
                    "memory_actions": [],
                }
            return {
                "response_type": "reply",
                "rationale": "Renfo d'hier saute, execution manquee.",
                "fitmas_message": "D'accord. Le footing ce matin, tu le sens ?",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.86,
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("J'ai pas eu le temps hier", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].target_ref, "seance d'hier")
        self.assertEqual(decision.execution_actions[0].status, "not_completed")

    def test_decide_repairs_invalid_execution_receipt_without_followup_id(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        invalid_payload = {
            "response_type": "no_change",
            "rationale": "User explique un imprevu hier, le renfo n'a pas ete fait.",
            "fitmas_message": "Vu pour hier. On garde le footing facile ce matin.",
            "memory_actions": [
                {
                    "type": "record_availability",
                    "window_text": "imprevu travail hier",
                    "availability": "limited",
                    "confidence": 0.75,
                }
            ],
        }

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            return dict(invalid_payload)

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("J'ai pas eu le temps hier", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].target_ref, "seance d'hier")
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertIs(decision.execution_actions[0].completed, False)
        self.assertGreaterEqual(len(prompts), 2)

    def test_decide_repairs_valid_non_completion_artifact_without_hier_word(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "reply",
                    "rationale": "User confirme qu'il n'a pas fait le renfo de mercredi (id=123).",
                    "fitmas_message": "Pas grave, on garde le footing facile ce matin.",
                    "memory_actions": [],
                }
            return {
                "response_type": "reply",
                "rationale": "Renfo de mercredi id=123 non realise.",
                "fitmas_message": "Pas grave, on garde le footing facile ce matin.",
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "renfo de mercredi",
                        "target_session_id": 123,
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.88,
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide("J'ai pas eu le temps", "Repere")
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].target_session_id, 123)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")

    def test_decide_repairs_missing_availability_memory_for_availability_intent(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "Piscine fermee deux semaines; aucune seance nage a modifier maintenant.",
                    "fitmas_message": "Piscine fermee deux semaines, c'est note. Je le garde pour les prochains plans.",
                    "memory_actions": [],
                }
            return {
                "response_type": "no_change",
                "rationale": "Piscine fermee deux semaines; contrainte disponible a memoriser.",
                "fitmas_message": "Piscine fermee deux semaines, c'est note. Je le garde pour les prochains plans.",
                "memory_actions": [
                    {
                        "type": "record_availability",
                        "window_text": "piscine fermee deux semaines",
                        "availability": "unavailable",
                        "confidence": 0.86,
                        "evidence": "piscine fermee deux semaines",
                    }
                ],
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "Ma piscine est fermee deux semaines",
                "Repere",
                coach_context={
                    "repair_memory_actions": True,
                    "turn_primary_intent": "availability_constraint",
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.memory_actions), 1)
        self.assertEqual(decision.memory_actions[0].type, "record_availability")
        self.assertIn("record_availability", prompts[1])

    def test_execution_compiler_uses_turn_plan_execution_claim(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "tour execution compris",
                    "fitmas_message": "Compris. On garde la suite simple.",
                }
            return {
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "sport_type": "running",
                        "confidence": 0.9,
                        "evidence": "execution_claim turn planner",
                    }
                ]
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "Pas eu le temps",
                "Repere",
                coach_context={
                    "turn_primary_intent": "execution_report",
                    "turn_plan": {
                        "primary_intent": "execution_report",
                        "execution_claim": {
                            "status": "not_done",
                            "sport_type": "running",
                            "date": "2026-05-11",
                        },
                    },
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].status, "not_completed")
        self.assertEqual(decision.execution_actions[0].sport_type, "running")
        self.assertIn("EXECUTION_COMPILER", prompts[1])
        self.assertIn("PlanPatch interdit", prompts[1])

    def test_health_memory_compiler_adds_resolved_health_action_only(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "signal sante compris sans adaptation planning",
                    "fitmas_message": "Bonne nouvelle. On reprend prudemment.",
                }
            return {
                "memory_actions": [
                    {
                        "action": "record_health_signal",
                        "health_signal": "douleur genou resolue",
                        "body_area": "genou",
                        "signal_kind": "pain",
                        "severity": "mild",
                        "status": "resolved",
                        "confidence": 0.9,
                        "evidence": "douleur passee",
                    }
                ]
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "La douleur est passee",
                "Repere",
                coach_context={
                    "turn_primary_intent": "health_signal",
                    "turn_plan": {"primary_intent": "health_signal"},
                    "selected_facts": [
                        {
                            "category": "health",
                            "key": "health_genou",
                            "value": "douleur genou",
                            "status": "ongoing",
                        }
                    ],
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.memory_actions), 1)
        self.assertEqual(decision.memory_actions[0].type, "record_health_signal")
        self.assertEqual(decision.memory_actions[0].status, "resolved")
        self.assertIsNone(decision.plan_patch)
        self.assertIn("HEALTH_MEMORY_COMPILER", prompts[1])
        self.assertIn("PlanPatch interdit", prompts[1])
        self.assertIn("meme si un plan_patch existe", prompts[1])
        self.assertIn('"action_expected_when_scope_confident": true', prompts[1])
        self.assertIn('"minimum_actions_when_scope_confident": 1', prompts[1])
        self.assertIn('"turn_intents": ["health_signal"]', prompts[1])
        self.assertIn("memory_actions=[] est autorise uniquement", prompts[1])

    def test_availability_memory_compiler_preserves_existing_plan_patch(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "requires_confirmation",
                    "rationale": "indisponibilite large, patch a confirmer",
                    "fitmas_message": "Je peux bouger la natation, mais je veux ton feu vert.",
                    "confirmation_reason": "deplacement sensible",
                    "plan_patch": {
                        "coach_message": "Je peux bouger la natation.",
                        "operations": [
                            {
                                "operation_type": "move_session",
                                "target_session_id": 44,
                                "target_date": "2099-05-20",
                                "rationale": "piscine indisponible",
                            }
                        ],
                    },
                }
            return {
                "memory_actions": [
                    {
                        "type": "record_availability",
                        "window_text": "natation impossible deux semaines",
                        "availability": "unavailable",
                        "confidence": 0.88,
                        "evidence": "je ne peux pas nager deux semaines",
                    }
                ]
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "Je ne peux pas nager deux semaines",
                "Repere",
                coach_context={
                    "repair_memory_actions": True,
                    "turn_primary_intent": "availability_constraint",
                    "turn_plan": {"primary_intent": "availability_constraint"},
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(decision.response_type, "requires_confirmation")
        self.assertIsNotNone(decision.plan_patch)
        self.assertEqual(len(decision.memory_actions), 1)
        self.assertEqual(decision.memory_actions[0].type, "record_availability")
        self.assertIn("AVAILABILITY_MEMORY_COMPILER", prompts[1])
        self.assertIn("PlanPatch interdit", prompts[1])
        self.assertIn('"action_expected_when_scope_confident": true', prompts[1])
        self.assertIn('"minimum_actions_when_scope_confident": 1', prompts[1])
        self.assertIn("memory_actions=[] est autorise uniquement", prompts[1])
        self.assertIn("aucune seance cible n'est necessaire", prompts[1])
        self.assertIn("plusieurs actions record_availability", prompts[1])
        self.assertIn("demain je suis dispo", prompts[1])

    def test_availability_memory_compiler_strict_retries_empty_first_pass(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        prompts: list[str] = []
        models: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            models.append(model)
            prompts.append(str(messages[0]["content"]))
            if len(prompts) == 1:
                return {
                    "response_type": "reply",
                    "rationale": "contrainte dispo comprise, cible planning ambigue",
                    "fitmas_message": "Je prefere clarifier la seance.",
                }
            if len(prompts) == 2:
                return {"memory_actions": []}
            return {
                "memory_actions": [
                    {
                        "action": "record_availability",
                        "window_text": "demain soir impossible",
                        "availability": "unavailable",
                        "confidence": 0.9,
                        "evidence": "contrainte dispo du tour",
                    }
                ]
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "Demain soir c'est impossible pour moi",
                "Repere",
                coach_context={
                    "turn_primary_intent": "availability_constraint",
                    "turn_plan": {"primary_intent": "availability_constraint"},
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsInstance(decision, llm.CoachDecision)
        self.assertEqual(len(decision.memory_actions), 1)
        self.assertEqual(decision.memory_actions[0].type, "record_availability")
        self.assertEqual(len(prompts), 3)
        self.assertIn("AVAILABILITY_MEMORY_COMPILER", prompts[1])
        self.assertIn("STRICT_AVAILABILITY_MEMORY_COMPILER", prompts[2])
        self.assertIn("cible planning est ambigue", prompts[2])
        self.assertEqual(models[1:], ["claude-sonnet-4-6", "claude-sonnet-4-6"])

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

    def test_tool_followup_prose_falls_back_to_format_retry_when_compiler_fails(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"count": 0}
        retry_prompts: list[str] = []
        structured_repair_calls = {"count": 0}

        def fake_request_message(
            *,
            system,
            messages,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            tools=None,
            tool_choice=None,
            **kwargs,
        ):
            calls["count"] += 1
            if calls["count"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={}),
                    ],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            if calls["count"] == 2:
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[
                        SimpleNamespace(
                            type="text",
                            text="Il n'y a pas de seance vendredi pour swapper. Tu voulais juste deplacer la natation ?",
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=180, output_tokens=48),
                )
            retry_prompts.append(str(messages[-1]["content"]))
            self.assertIsNone(tools)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"swap impossible sans seance cible vendredi","fitmas_message":"Il n’y a pas de seance vendredi pour echanger avec la natation. Tu veux plutot la deplacer a vendredi ?"}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=210, output_tokens=56),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(
                        tool_name=calls[0].tool_name,
                        status="ok",
                        payload={"sessions": [{"id": 1, "date": "2099-05-08", "title": "Natation"}]},
                        summary="Planning lu.",
                    ),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fail_structured_repair(*args, **kwargs):
            structured_repair_calls["count"] += 1
            return None

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fail_structured_repair
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "On peut swap la piscine de aujourd'hui avec vendredi ?",
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
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(calls["count"], 3)
        self.assertEqual(structured_repair_calls["count"], 3)
        self.assertIn("format", retry_prompts[0].lower())
        self.assertIn("json", retry_prompts[0].lower())

    def test_tool_followup_prose_repair_downgrades_free_confirmation_without_patch(self) -> None:
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "response_type": "requires_confirmation",
                "rationale": "propose une option mais aucun patch n'est structure",
                "fitmas_message": "Je peux echanger le tempo avec le renfo si tu confirmes.",
                "confirmation_reason": "swap a confirmer",
            }

        llm._request_structured_json = fake_request_structured_json
        try:
            data = llm._repair_decision_json_from_text(
                "Je peux echanger le tempo avec le renfo si tu confirmes.",
                context_prompt="Je ne suis pas dispo demain soir",
                tool_result_summary="- validate_plan_patch: Patch a confirmer.",
            )
        finally:
            llm._request_structured_json = original_request_structured_json

        self.assertEqual(data["response_type"], "no_change")
        self.assertIsNone(data.get("confirmation_reason"))
        self.assertNotIn("plan_patch", data)

    def test_invalid_payload_repair_downgrades_free_confirmation_without_patch(self) -> None:
        original_request_structured_json = llm._request_structured_json

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            return {
                "response_type": "requires_confirmation",
                "rationale": "aucune mutation structuree",
                "fitmas_message": "Je peux l'echanger avec mercredi si tu confirmes.",
                "confirmation_reason": "option a confirmer",
            }

        llm._request_structured_json = fake_request_structured_json
        try:
            data = llm._repair_invalid_decision_payload(
                data={
                    "response_type": "requires_confirmation",
                    "rationale": "aucune mutation structuree",
                    "fitmas_message": "Je peux l'echanger avec mercredi si tu confirmes.",
                    "confirmation_reason": "option a confirmer",
                },
                system="system",
                prompt="Je ne suis pas dispo demain soir",
            )
        finally:
            llm._request_structured_json = original_request_structured_json

        self.assertEqual(data["response_type"], "no_change")
        self.assertIsNone(data.get("confirmation_reason"))

    def test_tool_repair_context_includes_payloads_not_only_summaries(self) -> None:
        executions = [
            SimpleNamespace(
                result=ToolResult(
                    tool_name="get_plan_window",
                    status="ok",
                    summary="2 seances.",
                    payload={
                        "sessions": [
                            {"id": 11, "scheduled_date": "2099-03-23", "session_title": "Tempo"},
                            {"id": 12, "scheduled_date": "2099-03-25", "session_title": "Renfo"},
                        ]
                    },
                )
            )
        ]

        summary = llm._repair_tool_result_summary(executions)

        self.assertIn('"id": 11', summary)
        self.assertIn('"session_title": "Renfo"', summary)
        self.assertIn("2 seances.", summary)

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

    def test_tool_followup_dsml_markup_falls_back_to_format_retry_when_compiler_fails(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_execute_tool_calls = llm.execute_tool_calls
        original_request_structured_json = llm._request_structured_json
        original_log_tool_trace = llm.log_tool_trace
        calls = {"messages": 0, "structured": 0}
        retry_prompts: list[str] = []

        def fake_request_message(
            *,
            system,
            messages,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            tools=None,
            tool_choice=None,
            **kwargs,
        ):
            calls["messages"] += 1
            if calls["messages"] == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=32),
                )
            if calls["messages"] == 2:
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[
                        SimpleNamespace(
                            type="text",
                            text='Vérifions plus loin.<｜DSML｜tool_calls><｜DSML｜invoke name="get_full_calendar"></｜DSML｜invoke></｜DSML｜tool_calls>',
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=180, output_tokens=48),
                )
            retry_prompts.append(str(messages[-1]["content"]))
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"tool supplementaire non disponible, clarification sans inventer","fitmas_message":"Je ne vois pas de seance vendredi dans le calendrier lu. Tu veux plutot deplacer la natation sur ce creneau libre ?"}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=220, output_tokens=64),
            )

        def fake_execute_tool_calls(calls, *, context, **kwargs):
            return [
                SimpleNamespace(
                    result=ToolResult(
                        tool_name=calls[0].tool_name,
                        status="ok",
                        payload={"window": "week", "friday_sessions": []},
                        summary="Aucune seance vendredi dans la fenetre lue.",
                    ),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ]

        def fail_structured_repair(*args, **kwargs):
            calls["structured"] += 1
            return None

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.execute_tool_calls = fake_execute_tool_calls
        llm._request_structured_json = fail_structured_repair
        llm.log_tool_trace = lambda trace: None
        try:
            decision = llm.decide(
                "Swap piscine avec vendredi",
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
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(calls["messages"], 3)
        self.assertEqual(calls["structured"], 3)
        self.assertIn("tools", retry_prompts[0].lower())
        self.assertIn("json", retry_prompts[0].lower())

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
        system_prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            system_prompts.append(_system_text(system))
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
        self.assertIn("Source de verite planning conversationnelle", system_prompts[0])
        self.assertIn("Natation app truth", system_prompts[0])

    def test_decide_offers_plan_tools_for_app_plan_dispute(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual([tool["name"] for tool in tools], PLAN_LOOKUP_CONTRACT_TOOLS)
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
        self.assertEqual(traces[0].tool_count_offered, len(PLAN_LOOKUP_CONTRACT_TOOLS))

    def test_availability_turn_plan_intent_uses_dedicated_small_tool_budget(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        prompts: list[str] = []
        systems: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual([tool["name"] for tool in tools], AVAILABILITY_CONSTRAINT_TOOLS)
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
        self.assertEqual(traces[0].context_policy, "availability_constraint")
        self.assertEqual(traces[0].tool_count_offered, len(AVAILABILITY_CONSTRAINT_TOOLS))
        self.assertIn("Contexte orchestration planning", systems[0])
        self.assertIn("- route: conversation_availability_constraint", systems[0])
        self.assertNotIn("suggest_replan_candidates", systems[0])
        self.assertNotIn("draft_lighten_day", systems[0])
        self.assertNotIn("draft_replace_session", systems[0])

    def test_health_signal_intent_uses_small_health_tool_budget(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None):
            self.assertIsNotNone(tools)
            self.assertEqual([tool["name"] for tool in tools], HEALTH_SIGNAL_TOOLS)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"signal sante note","fitmas_message":"Je note le signal et je garde la seance prudente."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=160, output_tokens=36),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "J'ai une douleur tibia legere",
                "Repere",
                coach_context={"turn_primary_intent": "health_signal"},
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
        self.assertEqual(traces[0].context_policy, "health_signal")
        self.assertEqual(traces[0].tool_count_offered, len(HEALTH_SIGNAL_TOOLS))

    def test_close_turn_intent_offers_no_tools_even_with_tool_context(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        systems: list[str] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None, **kwargs):
            self.assertIsNone(tools)
            self.assertIsNone(tool_choice)
            systems.append("\n".join(part["text"] for part in system))
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"cloture sociale","fitmas_message":"Carre, on garde ca."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=80, output_tokens=24),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "Okay chef",
                "Repere",
                timeline_summary="- id=1 | date=2026-05-06 | Footing",
                execution_summary="Execution: planned_pending.",
                coach_context={
                    "turn_primary_intent": "close_turn",
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
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(traces, [])
        self.assertIn("- route: conversation_close_turn", systems[0])
        self.assertIn("- sortie decision: CoachDecision", systems[0])
        self.assertIn("Contrat de sortie terminal_text:", systems[0])
        self.assertNotIn("Workflow replan_after_constraint:", systems[0])
        self.assertNotIn("Actions possibles:", systems[0])
        self.assertNotIn("plan_patch = {", systems[0])
        self.assertNotIn("Calendrier daté utile", prompts[0])

    def test_casual_chat_intent_uses_casual_no_action_contract(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        traces: list[object] = []
        systems: list[str] = []
        prompts: list[str] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None, **kwargs):
            self.assertIsNone(tools)
            self.assertIsNone(tool_choice)
            systems.append("\n".join(part["text"] for part in system))
            prompts.append(messages[0]["content"] if isinstance(messages[0]["content"], str) else "")
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"reply","rationale":"conversation legere","fitmas_message":"Je te suis."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=80, output_tokens=24),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "Tu m'as fumé avec ton plan là",
                "Repere",
                timeline_summary="- id=1 | date=2026-05-06 | Footing",
                execution_summary="Execution: planned_pending.",
                coach_context={
                    "turn_primary_intent": "casual_chat",
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
        self.assertEqual(decision.response_type, "reply")
        self.assertEqual(traces, [])
        self.assertIn("- route: conversation_casual_chat", systems[0])
        self.assertIn("- sortie decision: CoachDecision", systems[0])
        self.assertIn("Contrat de sortie terminal_text:", systems[0])
        self.assertNotIn("Workflow replan_after_constraint:", systems[0])
        self.assertNotIn("Actions possibles:", systems[0])
        self.assertNotIn("plan_patch = {", systems[0])
        self.assertNotIn("Calendrier daté utile", prompts[0])

    def test_generic_question_can_offer_tools_but_excludes_planning_context_by_default(self) -> None:
        original_client = llm._client
        original_request_message = llm._request_message
        original_log_tool_trace = llm.log_tool_trace
        captured: dict[str, str] = {}
        traces: list[object] = []

        def fake_request_message(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=512, tools=None, tool_choice=None, **kwargs):
            self.assertEqual([tool["name"] for tool in tools or []], ["get_coach_lens", "get_relevant_facts"])
            captured["system"] = _system_text(system)
            captured["prompt"] = messages[0]["content"] if isinstance(messages[0]["content"], str) else ""
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"inquietude poids, pas de mutation planning","fitmas_message":"Ce n est pas grave en soi. On regarde la tendance et on reprend proprement."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=120, output_tokens=40),
            )

        llm._client = lambda: object()
        llm._request_message = fake_request_message
        llm.log_tool_trace = lambda trace: traces.append(trace)
        try:
            decision = llm.decide(
                "Putain je fais 100kg, qu'est-ce qu'on fait ?",
                "Repere legacy",
                timeline_summary="- Aujourd'hui 14h: Footing facile",
                execution_summary="Execution recente: aucune",
                tool_context=ToolContext(
                    pipeline="conversation",
                    user_id=1,
                    timezone_name="Europe/Paris",
                    scheduled_sessions=[],
                    activities=[],
                    active_facts=[],
                ),
                coach_context={"turn_primary_intent": "generic_question"},
            )
        finally:
            llm._client = original_client
            llm._request_message = original_request_message
            llm.log_tool_trace = original_log_tool_trace

        self.assertIsNotNone(decision)
        self.assertEqual(decision.response_type, "no_change")
        self.assertEqual(traces[0].context_policy, "generic_question_compact")
        self.assertEqual(traces[0].tool_count_offered, 2)
        self.assertNotIn("Footing facile", captured["prompt"])
        self.assertNotIn("14h", captured["prompt"])
        self.assertNotIn("Source de verite planning conversationnelle", captured["system"])
        self.assertIn("- route: conversation_generic_question", captured["system"])
        self.assertIn("ne recentre pas la reponse sur le planning", captured["system"])
        self.assertIn("get_coach_lens", captured["system"])
        self.assertIn("pas en formulaire", captured["system"])

    def test_memory_compiler_uses_turn_plan_secondary_availability_scope(self) -> None:
        original_client = llm._client
        original_request_structured_json = llm._request_structured_json
        calls: list[str] = []

        def fake_request_structured_json(*, system, messages, model="claude-haiku-4-5-20251001", max_tokens=1024):
            prompt = str(messages[0]["content"])
            calls.append(prompt)
            if len(calls) == 1:
                return {
                    "response_type": "no_change",
                    "rationale": "adaptation traitee ailleurs mais memoire oubliee",
                    "fitmas_message": "Je te propose une adaptation prudente.",
                    "memory_actions": [],
                }
            self.assertIn("AVAILABILITY_MEMORY_COMPILER", prompt)
            return {
                "memory_actions": [
                    {
                        "type": "record_availability",
                        "window_text": "natation impossible deux semaines",
                        "availability": "unavailable",
                        "sport_type": "swimming",
                        "starts_on": "2026-05-13",
                        "ends_on": "2026-05-27",
                        "confidence": 0.93,
                        "evidence": "Je ne peux pas nager pendant deux semaines",
                    }
                ]
            }

        llm._client = lambda: object()
        llm._request_structured_json = fake_request_structured_json
        try:
            decision = llm.decide(
                "Je ne peux pas nager pendant deux semaines, adapte si besoin.",
                "Repere",
                coach_context={
                    "turn_primary_intent": "plan_mutation",
                    "turn_plan": {
                        "primary_intent": "plan_mutation",
                        "secondary_intents": ["availability_constraint"],
                        "availability_constraint": {
                            "availability": "unavailable",
                            "sport_type": "swimming",
                            "starts_on": "2026-05-13",
                            "ends_on": "2026-05-27",
                        },
                    },
                },
            )
        finally:
            llm._client = original_client
            llm._request_structured_json = original_request_structured_json

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(decision.memory_actions), 1)
        self.assertEqual(decision.memory_actions[0].type, "record_availability")
        self.assertEqual(decision.memory_actions[0].sport_type, "swimming")

if __name__ == "__main__":
    unittest.main()
