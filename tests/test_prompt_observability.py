from fitmas.prompt_observability import (
    DecideFailureReason,
    build_prompt_trace,
    normalize_decide_failure_reason,
)
from fitmas import llm
from fitmas.context_pack import build_conversation_context_pack
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt
from fitmas.tool_contract import ToolContext
from fitmas.tools.routing import IntentCategory


def test_build_prompt_trace_counts_system_and_user_chars() -> None:
    trace = build_prompt_trace(
        route="conversation_decide",
        provider="deepseek",
        model="deepseek-chat",
        prompt_policy="plan_lookup_compact",
        prompt_contract=None,
        intent="plan_lookup",
        system=[{"type": "text", "text": "system A"}, {"type": "text", "text": "system B"}],
        user_prompt="hello user",
        tool_names=("get_plan_window",),
        truth_block_names=("temporal", "planning"),
        history_messages_used=2,
    )

    assert trace.route == "conversation_decide"
    assert trace.system_chars == len("system A") + len("system B")
    assert trace.user_chars == len("hello user")
    assert trace.total_chars == trace.system_chars + trace.user_chars
    assert trace.tool_names == ("get_plan_window",)
    assert trace.truth_block_names == ("temporal", "planning")
    assert trace.history_messages_used == 2


def test_normalize_decide_failure_reason_accepts_known_values_only() -> None:
    assert normalize_decide_failure_reason("empty_output") == DecideFailureReason.EMPTY_OUTPUT
    assert normalize_decide_failure_reason("not-a-real-reason") == DecideFailureReason.UNKNOWN


def test_layered_prompt_bundle_exposes_trace_metadata() -> None:
    policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    context_pack = build_conversation_context_pack(
        route="conversation_plan_lookup",
        intent="plan_lookup",
        capability="read_only",
        time_context={"today": "vendredi"},
        temporal_summary="Aujourd'hui: vendredi",
        timeline_summary="- Vendredi: Footing 40 min",
        allowed_tools=("get_plan_window",),
    )
    bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi",
        timeline_summary="- Vendredi: Footing 40 min",
        execution_summary=None,
        temporal_summary=None,
        activity_claim_summary=None,
        signal_summary=None,
        conversation_history=[],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=[],
        context_pack=context_pack,
    )

    assert bundle.trace is not None
    assert bundle.trace.prompt_policy == "plan_lookup_compact"
    assert bundle.trace.prompt_contract == "conversation_plan_lookup"
    assert bundle.trace.intent == "plan_lookup"
    assert bundle.trace.tool_names == ("get_plan_window",)
    assert bundle.trace.truth_block_names == context_pack.truth_block_names()
    assert bundle.trace.total_chars > 0


def test_decide_none_trace_records_schema_repair_and_fallback_events(monkeypatch) -> None:
    invalid_payload = {
        "response_type": "no_change",
        "rationale": "ok",
        "fitmas_message": "Je deplace la seance.",
    }

    monkeypatch.setattr(llm, "_client", lambda: object())
    monkeypatch.setattr(llm, "_request_structured_json", lambda **_kwargs: dict(invalid_payload))

    decision = llm.decide("deplace ca", "plan")
    trace = llm.get_last_decide_none()

    assert decision is None
    assert trace is not None
    assert trace["reason"] == "fallback_failed"
    assert [event["reason"] for event in trace["events"]] == [
        "schema_invalid",
        "repair_failed",
        "fallback_failed",
    ]


def test_decide_none_trace_records_tool_loop_then_empty_output(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_client", lambda: object())
    monkeypatch.setattr(llm, "_request_json_with_tools", lambda **_kwargs: None)
    monkeypatch.setattr(llm, "_request_structured_json", lambda **_kwargs: None)

    decision = llm.decide(
        "redonne le plan actuel",
        "plan",
        tool_context=ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
        ),
    )
    trace = llm.get_last_decide_none()

    assert decision is None
    assert trace is not None
    assert trace["reason"] == "empty_output"
    assert [event["reason"] for event in trace["events"]] == [
        "tool_loop_failed",
        "empty_output",
    ]
