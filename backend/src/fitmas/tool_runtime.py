from __future__ import annotations

import logging
from time import perf_counter

from fitmas.tool_contract import ToolCall, ToolContext, ToolResult
from fitmas.tool_metrics import ToolTrace, build_tool_trace, log_tool_trace
from fitmas.tool_registry import build_tool_registry

logger = logging.getLogger(__name__)


def execute_tool_call(
    call: ToolCall,
    *,
    context: ToolContext,
    fallback_used: bool = False,
    llm_round_trips: int = 1,
    prompt_tokens_estimate: int | None = None,
    response_tokens_estimate: int | None = None,
) -> tuple[ToolResult, ToolTrace]:
    registry = build_tool_registry()
    spec = registry.get(call.tool_name)
    if spec is None:
        result = ToolResult(
            tool_name=call.tool_name,
            status="error",
            error=f"Unknown tool: {call.tool_name}",
        )
        trace = build_tool_trace(
            pipeline=context.pipeline,
            tool_name=call.tool_name,
            tool_requested=True,
            tool_called=False,
            tool_success=False,
            tool_error=result.error,
            fallback_used=fallback_used,
            llm_round_trips=llm_round_trips,
            prompt_tokens_estimate=prompt_tokens_estimate,
            response_tokens_estimate=response_tokens_estimate,
        )
        log_tool_trace(trace, logger=logger)
        return result, trace

    if context.pipeline not in spec.allowed_pipelines or spec.handler is None:
        result = ToolResult(
            tool_name=call.tool_name,
            status="error",
            error=f"Tool {call.tool_name} not allowed on pipeline {context.pipeline}",
        )
        trace = build_tool_trace(
            pipeline=context.pipeline,
            tool_name=call.tool_name,
            tool_requested=True,
            tool_called=False,
            tool_success=False,
            tool_error=result.error,
            fallback_used=fallback_used,
            llm_round_trips=llm_round_trips,
            prompt_tokens_estimate=prompt_tokens_estimate,
            response_tokens_estimate=response_tokens_estimate,
        )
        log_tool_trace(trace, logger=logger)
        return result, trace

    started_at = perf_counter()
    try:
        result = spec.handler(context, call.arguments)
        latency_ms = int((perf_counter() - started_at) * 1000)
        trace = build_tool_trace(
            pipeline=context.pipeline,
            tool_name=call.tool_name,
            tool_requested=True,
            tool_called=True,
            tool_latency_ms=latency_ms,
            tool_success=result.status == "ok",
            tool_error=result.error,
            fallback_used=fallback_used,
            llm_round_trips=llm_round_trips,
            prompt_tokens_estimate=prompt_tokens_estimate,
            response_tokens_estimate=response_tokens_estimate,
            total_duration_ms=latency_ms,
        )
        log_tool_trace(trace, logger=logger)
        return result, trace
    except Exception as exc:
        latency_ms = int((perf_counter() - started_at) * 1000)
        result = ToolResult(
            tool_name=call.tool_name,
            status="error",
            error=str(exc),
        )
        trace = build_tool_trace(
            pipeline=context.pipeline,
            tool_name=call.tool_name,
            tool_requested=True,
            tool_called=True,
            tool_latency_ms=latency_ms,
            tool_success=False,
            tool_error=str(exc),
            fallback_used=fallback_used,
            llm_round_trips=llm_round_trips,
            prompt_tokens_estimate=prompt_tokens_estimate,
            response_tokens_estimate=response_tokens_estimate,
            total_duration_ms=latency_ms,
        )
        log_tool_trace(trace, logger=logger)
        return result, trace
