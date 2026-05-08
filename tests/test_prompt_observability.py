from fitmas.prompt_observability import (
    DecideFailureReason,
    build_prompt_trace,
    normalize_decide_failure_reason,
)


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
        history_messages_used=2,
    )

    assert trace.route == "conversation_decide"
    assert trace.system_chars == len("system A") + len("system B")
    assert trace.user_chars == len("hello user")
    assert trace.total_chars == trace.system_chars + trace.user_chars
    assert trace.tool_names == ("get_plan_window",)
    assert trace.history_messages_used == 2


def test_normalize_decide_failure_reason_accepts_known_values_only() -> None:
    assert normalize_decide_failure_reason("empty_output") == DecideFailureReason.EMPTY_OUTPUT
    assert normalize_decide_failure_reason("not-a-real-reason") == DecideFailureReason.UNKNOWN
