from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ToolTrace:
    pipeline: str
    tool_name: str | None
    tool_requested: bool
    tool_called: bool
    tool_latency_ms: int | None
    tool_success: bool
    tool_offered: bool = False
    context_policy: str | None = None
    tool_error: str | None = None
    fallback_used: bool = False
    llm_round_trips: int = 1
    tool_count_offered: int | None = None
    history_messages_used: int | None = None
    prompt_char_count: int | None = None
    prompt_tokens_estimate: int | None = None
    response_tokens_estimate: int | None = None
    total_duration_ms: int | None = None
    response_stop_reason: str | None = None
    created_at: str = ""


def build_tool_trace(
    *,
    pipeline: str,
    tool_name: str | None = None,
    tool_offered: bool = False,
    context_policy: str | None = None,
    tool_requested: bool = True,
    tool_called: bool = True,
    tool_latency_ms: int | None = None,
    tool_success: bool,
    tool_error: str | None = None,
    fallback_used: bool = False,
    llm_round_trips: int = 1,
    tool_count_offered: int | None = None,
    history_messages_used: int | None = None,
    prompt_char_count: int | None = None,
    prompt_tokens_estimate: int | None = None,
    response_tokens_estimate: int | None = None,
    total_duration_ms: int | None = None,
    response_stop_reason: str | None = None,
) -> ToolTrace:
    return ToolTrace(
        pipeline=pipeline,
        tool_name=tool_name,
        tool_offered=tool_offered,
        context_policy=context_policy,
        tool_requested=tool_requested,
        tool_called=tool_called,
        tool_latency_ms=tool_latency_ms,
        tool_success=tool_success,
        tool_error=tool_error,
        fallback_used=fallback_used,
        llm_round_trips=llm_round_trips,
        tool_count_offered=tool_count_offered,
        history_messages_used=history_messages_used,
        prompt_char_count=prompt_char_count,
        prompt_tokens_estimate=prompt_tokens_estimate,
        response_tokens_estimate=response_tokens_estimate,
        total_duration_ms=total_duration_ms,
        response_stop_reason=response_stop_reason,
        created_at=_utc_now_iso(),
    )


def log_tool_trace(trace: ToolTrace, *, logger: logging.Logger | None = None) -> None:
    target_logger = logger or logging.getLogger("fitmas.tool_metrics")
    target_logger.info("tool_trace=%s", json.dumps(asdict(trace), ensure_ascii=False, sort_keys=True))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
