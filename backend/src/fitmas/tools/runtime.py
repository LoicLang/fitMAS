from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import perf_counter

from fitmas.tools.contract import ToolCall, ToolContext, ToolResult
from fitmas.tools.metrics import ToolTrace, build_tool_trace, log_tool_trace
from fitmas.tools.registry import build_tool_registry

logger = logging.getLogger(__name__)

TOOL_DUPLICATE_CACHED = "tool_duplicate_cached"


@dataclass(frozen=True, slots=True)
class ToolExecution:
    result: ToolResult
    trace: ToolTrace


def count_budgeted_tool_executions(executions: list[ToolExecution]) -> int:
    """Count real tool executions that should consume the per-turn budget."""
    return sum(
        1
        for execution in executions
        if execution.result.error != "tool_budget_exceeded"
        and getattr(execution.trace, "tool_error", None) != TOOL_DUPLICATE_CACHED
    )


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

        # --- Post-tool hooks ---
        result = _run_post_tool_hooks(result, call=call, context=context, latency_ms=latency_ms)

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


def execute_tool_calls(
    calls: list[ToolCall],
    *,
    context: ToolContext,
    max_tools: int = 3,
    fallback_used: bool = False,
    llm_round_trips: int = 1,
    prompt_tokens_estimate: int | None = None,
    response_tokens_estimate: int | None = None,
    result_cache: dict[str, ToolExecution] | None = None,
) -> list[ToolExecution]:
    """Execute a bounded batch of tools and preserve one result per call."""
    executions: list[ToolExecution] = []
    budget = max(0, max_tools)
    budget_used = 0
    cache = result_cache if result_cache is not None else {}
    for call in calls:
        cache_key = _tool_cache_key(call)
        cached_execution = cache.get(cache_key)
        if cached_execution is not None:
            executions.append(
                _cached_tool_execution(
                    cached_execution,
                    context=context,
                    fallback_used=fallback_used,
                    llm_round_trips=llm_round_trips,
                    prompt_tokens_estimate=prompt_tokens_estimate,
                    response_tokens_estimate=response_tokens_estimate,
                )
            )
            continue

        if budget_used >= budget:
            result = ToolResult(
                tool_name=call.tool_name,
                status="error",
                error="tool_budget_exceeded",
                summary=f"Tool non execute: budget de {budget} tools atteint.",
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
            executions.append(ToolExecution(result=result, trace=trace))
            continue

        result, trace = execute_tool_call(
            call,
            context=context,
            fallback_used=fallback_used,
            llm_round_trips=llm_round_trips,
            prompt_tokens_estimate=prompt_tokens_estimate,
            response_tokens_estimate=response_tokens_estimate,
        )
        execution = ToolExecution(result=result, trace=trace)
        executions.append(execution)
        cache[cache_key] = execution
        budget_used += 1
    return executions


def _tool_cache_key(call: ToolCall) -> str:
    arguments = json.dumps(call.arguments, sort_keys=True, default=str, ensure_ascii=True)
    return f"{call.tool_name}:{arguments}"


def _cached_tool_execution(
    cached_execution: ToolExecution,
    *,
    context: ToolContext,
    fallback_used: bool,
    llm_round_trips: int,
    prompt_tokens_estimate: int | None,
    response_tokens_estimate: int | None,
) -> ToolExecution:
    cached_result = cached_execution.result
    summary = cached_result.summary or "Resultat tool deja lu dans ce tour."
    if "deja lu" not in summary.lower():
        summary = f"{summary} [Resultat deja lu dans ce tour; reutilise sans nouvel appel.]"
    result = ToolResult(
        tool_name=cached_result.tool_name,
        status=cached_result.status,
        payload=cached_result.payload,
        summary=summary,
        error=cached_result.error,
    )
    trace = build_tool_trace(
        pipeline=context.pipeline,
        tool_name=result.tool_name,
        tool_requested=True,
        tool_called=False,
        tool_success=result.status == "ok",
        tool_error=TOOL_DUPLICATE_CACHED,
        fallback_used=fallback_used,
        llm_round_trips=llm_round_trips,
        prompt_tokens_estimate=prompt_tokens_estimate,
        response_tokens_estimate=response_tokens_estimate,
    )
    log_tool_trace(trace, logger=logger)
    return ToolExecution(result=result, trace=trace)


# ---------------------------------------------------------------------------
# Post-tool hooks
# ---------------------------------------------------------------------------

def _run_post_tool_hooks(
    result: ToolResult,
    *,
    call: ToolCall,
    context: ToolContext,
    latency_ms: int,
) -> ToolResult:
    """Run post-execution hooks that can annotate or enrich the result."""
    result = _annotate_empty_result(result)
    result = _annotate_freshness(result, latency_ms=latency_ms)
    return result


def _annotate_empty_result(result: ToolResult) -> ToolResult:
    """Detect empty/degraded results and annotate the summary for the LLM."""
    if result.status != "ok":
        return result

    payload = result.payload
    is_empty = False

    # Check common payload shapes for emptiness
    if not payload:
        is_empty = True
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list) and not value:
                is_empty = True
                break

    if is_empty:
        return ToolResult(
            tool_name=result.tool_name,
            status="ok",
            payload=result.payload,
            summary=result.summary + " [Aucune donnee trouvee — le resultat est vide.]",
            error=result.error,
        )
    return result


def _annotate_freshness(result: ToolResult, *, latency_ms: int) -> ToolResult:
    """Add latency annotation for slow tool calls."""
    if latency_ms > 500:
        return ToolResult(
            tool_name=result.tool_name,
            status=result.status,
            payload=result.payload,
            summary=result.summary + f" [latence: {latency_ms}ms]",
            error=result.error,
        )
    return result
