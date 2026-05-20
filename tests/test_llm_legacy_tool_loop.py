from __future__ import annotations

from types import SimpleNamespace

import fitmas.llm.legacy_tool_loop as legacy_tool_loop
from fitmas.tools.contract import ToolContext, ToolResult


def _context() -> ToolContext:
    return ToolContext(
        pipeline="conversation",
        user_id=1,
        timezone_name="Europe/Paris",
        scheduled_sessions=[],
        activities=[],
        active_facts=[],
    )


def test_legacy_tool_loop_completes_single_tool_round_trip() -> None:
    calls = {"messages": 0, "structured": 0}
    traces: list[object] = []

    def request_message_fn(**kwargs):
        calls["messages"] += 1
        if calls["messages"] == 1:
            assert kwargs["tools"]
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})
                ],
                usage=SimpleNamespace(input_tokens=12, output_tokens=4),
            )
        assert kwargs["messages"][-1]["content"][0]["type"] == "tool_result"
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="Je vois la sortie running.")],
            usage=SimpleNamespace(input_tokens=24, output_tokens=8),
        )

    def execute_tool_calls_fn(calls_arg, *, context, **_kwargs):
        assert context.pipeline == "conversation"
        assert calls_arg[0].tool_name == "get_plan_window"
        return [
            SimpleNamespace(
                result=ToolResult(
                    tool_name="get_plan_window",
                    status="ok",
                    payload={"sessions": [{"id": 7, "session_title": "Sortie running"}]},
                    summary="Une seance trouvee.",
                ),
                trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=3),
            )
        ]

    def request_structured_json_fn(**kwargs):
        calls["structured"] += 1
        prompt = str(kwargs["messages"][0]["content"])
        assert "RESULTATS_TOOLS" in prompt
        assert '"id": 7' in prompt
        return {
            "response_type": "no_change",
            "rationale": "decision compilee depuis tools",
            "fitmas_message": "Je vois la sortie running.",
        }

    data = legacy_tool_loop.request_json_with_tools(
        system="system",
        prompt="prompt",
        tool_context=_context(),
        tool_names=("get_plan_window",),
        context_policy="plan_lookup_compact",
        history_messages_used=0,
        dependencies=legacy_tool_loop.LegacyToolLoopDependencies(
            request_message_fn=request_message_fn,
            request_structured_json_fn=request_structured_json_fn,
            execute_tool_calls_fn=execute_tool_calls_fn,
            log_tool_trace_fn=lambda trace: traces.append(trace),
            tool_thinking_kwargs_fn=lambda: {},
        ),
    )

    assert data is not None
    assert data["fitmas_message"] == "Je vois la sortie running."
    assert calls == {"messages": 2, "structured": 1}
    assert len(traces) == 1
    assert traces[0].tool_requested is True
    assert traces[0].tool_called is True
    assert traces[0].tool_name == "get_plan_window"


def test_legacy_tool_loop_compiler_failure_falls_back_to_tool_phase_json() -> None:
    calls = {"messages": 0, "structured": 0}

    def request_message_fn(**_kwargs):
        calls["messages"] += 1
        if calls["messages"] == 1:
            return SimpleNamespace(
                stop_reason="tool_use",
                content=[SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={})],
                usage=SimpleNamespace(input_tokens=12, output_tokens=4),
            )
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(
                    type="text",
                    text='{"response_type":"no_change","rationale":"fallback direct","fitmas_message":"Je garde la reponse directe."}',
                )
            ],
            usage=SimpleNamespace(input_tokens=24, output_tokens=8),
        )

    def request_structured_json_fn(**_kwargs):
        calls["structured"] += 1
        raise RuntimeError("compiler provider unavailable")

    data = legacy_tool_loop.request_json_with_tools(
        system="system",
        prompt="prompt",
        tool_context=_context(),
        tool_names=("get_plan_window",),
        context_policy="plan_lookup_compact",
        history_messages_used=0,
        dependencies=legacy_tool_loop.LegacyToolLoopDependencies(
            request_message_fn=request_message_fn,
            request_structured_json_fn=request_structured_json_fn,
            execute_tool_calls_fn=lambda calls_arg, **_kwargs: [
                SimpleNamespace(
                    result=ToolResult(
                        tool_name=calls_arg[0].tool_name,
                        status="ok",
                        payload={"sessions": []},
                        summary="Plan lu.",
                    ),
                    trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
                )
            ],
            log_tool_trace_fn=lambda _trace: None,
            tool_thinking_kwargs_fn=lambda: {},
        ),
    )

    assert data is not None
    assert data["fitmas_message"] == "Je garde la reponse directe."
    assert calls == {"messages": 2, "structured": 1}


def test_legacy_tool_loop_satisfies_every_tool_use_block() -> None:
    blocks = [
        SimpleNamespace(type="tool_use", id="toolu_1", name="get_plan_window", input={}),
        SimpleNamespace(type="tool_use", id="toolu_2", name="get_user_constraints", input={}),
    ]
    executions = [
        SimpleNamespace(
            result=ToolResult(tool_name="get_plan_window", status="ok", payload={}, summary="Plan lu."),
            trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
        ),
        SimpleNamespace(
            result=ToolResult(tool_name="get_user_constraints", status="ok", payload={}, summary="Contraintes lues."),
            trace=SimpleNamespace(tool_success=True, tool_called=True, tool_latency_ms=1),
        ),
    ]

    result_blocks = legacy_tool_loop.tool_result_blocks(blocks, executions)

    assert [block["tool_use_id"] for block in result_blocks] == ["toolu_1", "toolu_2"]
    assert all(block["type"] == "tool_result" for block in result_blocks)


def test_legacy_tool_loop_logs_offered_but_not_requested_when_no_tool_use() -> None:
    traces: list[object] = []

    data = legacy_tool_loop.request_json_with_tools(
        system="system",
        prompt="prompt",
        tool_context=_context(),
        tool_names=("get_plan_window",),
        context_policy="plan_lookup_compact",
        history_messages_used=0,
        dependencies=legacy_tool_loop.LegacyToolLoopDependencies(
            request_message_fn=lambda **_kwargs: SimpleNamespace(
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"response_type":"no_change","rationale":"direct","fitmas_message":"Plan lu."}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            ),
            request_structured_json_fn=lambda **_kwargs: None,
            execute_tool_calls_fn=lambda *_args, **_kwargs: [],
            log_tool_trace_fn=lambda trace: traces.append(trace),
            tool_thinking_kwargs_fn=lambda: {},
        ),
    )

    assert data is not None
    assert data["fitmas_message"] == "Plan lu."
    assert len(traces) == 1
    assert traces[0].tool_offered is True
    assert traces[0].tool_requested is False
    assert traces[0].tool_called is False
    assert traces[0].response_stop_reason == "end_turn"
