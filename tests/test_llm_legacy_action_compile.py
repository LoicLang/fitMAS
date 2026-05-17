from __future__ import annotations

from fitmas.llm.legacy_action_compile import (
    maybe_compile_execution_actions_for_turn,
    maybe_compile_memory_actions_for_turn,
)
from fitmas.llm.legacy_models import CoachDecision


def test_legacy_action_compile_injects_request_function_for_execution_actions() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="execution a compiler",
        fitmas_message="Je note la seance d'hier.",
    )
    calls: list[dict] = []

    def request_structured_json_fn(**kwargs):
        calls.append(kwargs)
        return {
            "execution_actions": [
                {
                    "type": "record_execution_update",
                    "target_session_id": 77,
                    "completed": False,
                    "confidence": "high",
                }
            ]
        }

    compiled = maybe_compile_execution_actions_for_turn(
        decision=decision,
        system="system",
        prompt="prompt original",
        coach_context={
            "turn_primary_intent": "execution_report",
            "turn_execution_claim": {"status": "not_done"},
        },
        request_structured_json_fn=request_structured_json_fn,
    )

    assert len(calls) == 1
    assert compiled.execution_actions[0].target_ref == "session_id:77"
    assert compiled.execution_actions[0].status == "not_completed"


def test_legacy_action_compile_injects_request_function_for_memory_actions() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="memoire a compiler",
        fitmas_message="Je garde la contrainte en tete.",
    )
    calls: list[dict] = []

    def request_structured_json_fn(**kwargs):
        calls.append(kwargs)
        return {
            "memory_actions": [
                {
                    "type": "record_availability",
                    "window_text": "demain soir impossible",
                    "availability": "unavailable",
                    "confidence": "medium",
                }
            ]
        }

    compiled = maybe_compile_memory_actions_for_turn(
        decision=decision,
        system="system",
        prompt="prompt original",
        coach_context={"turn_primary_intent": "availability_constraint"},
        request_structured_json_fn=request_structured_json_fn,
    )

    assert len(calls) == 1
    assert compiled.memory_actions[0].type == "record_availability"
    assert compiled.memory_actions[0].confidence == 0.65
