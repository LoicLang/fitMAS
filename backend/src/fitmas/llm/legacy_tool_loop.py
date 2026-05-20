from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from time import perf_counter
from typing import Any, Callable

from . import gateway as gw
from . import legacy_parser, legacy_schema_repair
from fitmas.tools.contract import ToolCall, ToolContext
from fitmas.tools.metrics import build_tool_trace
from fitmas.tools.registry import list_tools_for_pipeline
from fitmas.tools.runtime import ToolExecution, count_budgeted_tool_executions


logger = logging.getLogger("fitmas.llm")


@dataclass(frozen=True)
class LegacyToolLoopDependencies:
    request_message_fn: Callable[..., Any | None]
    request_structured_json_fn: Callable[..., dict | None]
    execute_tool_calls_fn: Callable[..., list[Any]]
    log_tool_trace_fn: Callable[..., None]
    tool_thinking_kwargs_fn: Callable[[], dict[str, Any]]


def request_json_with_tools(
    *,
    system: str,
    prompt: str,
    tool_context: ToolContext,
    tool_names: tuple[str, ...],
    context_policy: str,
    history_messages_used: int,
    dependencies: LegacyToolLoopDependencies,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
) -> dict | None:
    tools = list_tools_for_pipeline(tool_context.pipeline, tool_names=tool_names)
    if not tools:
        return None
    started_at = perf_counter()
    prompt_char_count = len(prompt)
    tool_count_offered = len(tools)
    messages = [{"role": "user", "content": prompt}]
    max_tool_rounds = 3
    max_tool_calls_total = 6
    tool_rounds = 0
    tool_calls_used = 0
    tool_executions: list[Any] = []
    tool_result_cache: dict[str, ToolExecution] = {}
    prompt_token_values: list[int | None] = []
    response_token_values: list[int | None] = []
    response = dependencies.request_message_fn(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice={"type": "auto"},
        **dependencies.tool_thinking_kwargs_fn(),
    )
    if response is None:
        log_tool_session_trace(
            pipeline=tool_context.pipeline,
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=False,
            tool_called=False,
            tool_success=False,
            fallback_used=True,
            llm_round_trips=1,
            tool_count_offered=tool_count_offered,
            history_messages_used=history_messages_used,
            prompt_char_count=prompt_char_count,
            total_duration_ms=gw.elapsed_ms(started_at),
            response_stop_reason="initial_request_failed",
            log_tool_trace_fn=dependencies.log_tool_trace_fn,
        )
        return None

    round_trips = 1
    while True:
        stop_reason = str(getattr(response, "stop_reason", "") or "")
        prompt_token_values.append(gw.usage_value(response, "input_tokens"))
        response_token_values.append(gw.usage_value(response, "output_tokens"))

        if stop_reason != "tool_use":
            raw_text_for_repair = gw.message_text(response)
            compiler_succeeded = False
            data = None
            if tool_executions:
                round_trips += 1
                data = compile_tool_decision_json(
                    system=system,
                    prompt=prompt,
                    raw_tool_phase_text=raw_text_for_repair,
                    tool_executions=tool_executions,
                    model=model,
                    max_tokens=max_tokens,
                    request_structured_json_fn=dependencies.request_structured_json_fn,
                )
                compiler_succeeded = data is not None
            if data is None:
                data = gw.message_json(response)
            if tool_executions and data is None:
                retry_response = retry_tool_followup_json_format(
                    system=system,
                    messages=messages,
                    response=response,
                    model=model,
                    max_tokens=max_tokens,
                    request_message_fn=dependencies.request_message_fn,
                    tool_thinking_kwargs_fn=dependencies.tool_thinking_kwargs_fn,
                )
                if retry_response is not None:
                    round_trips += 1
                    prompt_token_values.append(gw.usage_value(retry_response, "input_tokens"))
                    response_token_values.append(gw.usage_value(retry_response, "output_tokens"))
                    retry_data = gw.message_json(retry_response)
                    if retry_data is not None:
                        data = retry_data
                    else:
                        raw_text_for_repair = gw.message_text(retry_response) or raw_text_for_repair
            if tool_executions and data is None:
                data = legacy_schema_repair.repair_decision_json_from_text(
                    raw_text_for_repair,
                    model=model,
                    context_prompt=prompt,
                    tool_result_summary=legacy_schema_repair.repair_tool_result_summary(tool_executions),
                    request_structured_json_fn=dependencies.request_structured_json_fn,
                    downgrade_free_confirmation_fn=legacy_parser.downgrade_free_confirmation_payload,
                )
            log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_name=tool_execution_names(tool_executions),
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=bool(tool_executions),
                tool_called=any_tool_called(tool_executions),
                tool_latency_ms=sum_tool_latency(tool_executions),
                tool_success=(
                    data is not None
                    and (not tool_executions or all_tool_results_ok(tool_executions))
                ),
                tool_error=(
                    tool_errors(tool_executions)
                    if data is not None
                    else (tool_errors(tool_executions) or "tool followup response was not valid JSON")
                ),
                fallback_used=data is None,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=sum_optional_ints(prompt_token_values),
                response_tokens_estimate=sum_optional_ints(response_token_values),
                total_duration_ms=gw.elapsed_ms(started_at),
                response_stop_reason="tool_compiler_json" if compiler_succeeded else (stop_reason or "end_turn"),
                log_tool_trace_fn=dependencies.log_tool_trace_fn,
            )
            return data

        tool_use_blocks = tool_use_blocks_from_response(response)
        if not tool_use_blocks:
            data = gw.message_json(response)
            log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=True,
                tool_called=any_tool_called(tool_executions),
                tool_success=data is not None,
                tool_error="tool_use stop_reason without tool block",
                fallback_used=True,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=sum_optional_ints(prompt_token_values),
                response_tokens_estimate=sum_optional_ints(response_token_values),
                total_duration_ms=gw.elapsed_ms(started_at),
                response_stop_reason=stop_reason or "tool_use",
                log_tool_trace_fn=dependencies.log_tool_trace_fn,
            )
            return data

        tool_rounds += 1
        remaining_tool_budget = max(0, max_tool_calls_total - tool_calls_used)
        tool_calls = [
            ToolCall(tool_name=str(getattr(block, "name", "")), arguments=dict(getattr(block, "input", {}) or {}))
            for block in tool_use_blocks
        ]
        round_executions = dependencies.execute_tool_calls_fn(
            tool_calls,
            context=tool_context,
            max_tools=remaining_tool_budget,
            llm_round_trips=round_trips + 1,
            prompt_tokens_estimate=sum_optional_ints(prompt_token_values),
            response_tokens_estimate=sum_optional_ints(response_token_values),
            result_cache=tool_result_cache,
        )
        tool_calls_used += count_budgeted_tool_executions(round_executions)
        tool_executions.extend(round_executions)
        messages.append({"role": "assistant", "content": gw.serialize_content_blocks(getattr(response, "content", []))})
        messages.append({"role": "user", "content": tool_followup_content(tool_use_blocks, round_executions)})

        allow_more_tools = tool_rounds < max_tool_rounds and tool_calls_used < max_tool_calls_total
        response = dependencies.request_message_fn(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            tools=tools if allow_more_tools else None,
            tool_choice={"type": "auto"} if allow_more_tools else None,
            **dependencies.tool_thinking_kwargs_fn(),
        )
        round_trips += 1
        if response is None:
            log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_name=tool_execution_names(tool_executions),
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=True,
                tool_called=any_tool_called(tool_executions),
                tool_latency_ms=sum_tool_latency(tool_executions),
                tool_success=False,
                tool_error=tool_errors(tool_executions) or "tool followup request failed",
                fallback_used=True,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=sum_optional_ints(prompt_token_values),
                response_tokens_estimate=sum_optional_ints(response_token_values),
                total_duration_ms=gw.elapsed_ms(started_at),
                response_stop_reason="followup_request_failed",
                log_tool_trace_fn=dependencies.log_tool_trace_fn,
            )
            return None

    log_tool_session_trace(
        pipeline=tool_context.pipeline,
        tool_name=tool_execution_names(tool_executions),
        tool_offered=True,
        context_policy=context_policy,
        tool_requested=True,
        tool_called=any_tool_called(tool_executions),
        tool_latency_ms=sum_tool_latency(tool_executions),
        tool_success=False,
        tool_error=tool_errors(tool_executions) or "tool loop exhausted",
        fallback_used=True,
        llm_round_trips=round_trips,
        tool_count_offered=tool_count_offered,
        history_messages_used=history_messages_used,
        prompt_char_count=prompt_char_count,
        prompt_tokens_estimate=sum_optional_ints(prompt_token_values),
        response_tokens_estimate=sum_optional_ints(response_token_values),
        total_duration_ms=gw.elapsed_ms(started_at),
        response_stop_reason="tool_loop_exhausted",
        log_tool_trace_fn=dependencies.log_tool_trace_fn,
    )
    return None


def compile_tool_decision_json(
    *,
    system: str,
    prompt: str,
    raw_tool_phase_text: str | None,
    tool_executions: list[Any],
    model: str,
    max_tokens: int,
    request_structured_json_fn: Callable[..., dict | None],
) -> dict | None:
    tool_result_summary = legacy_schema_repair.repair_tool_result_summary(tool_executions, payload_char_limit=6000)
    if not tool_result_summary:
        return None
    raw_block = (raw_tool_phase_text or "").strip() or "(vide)"
    compiler_prompt = (
        "Compile la decision finale FitMAS depuis le contexte original et les resultats de tools.\n"
        "Cette phase ne parle pas a l'utilisateur: elle produit seulement le JSON final.\n\n"
        "REGLES:\n"
        "- n'appelle aucun tool; tous les tools autorises pour ce tour sont deja termines\n"
        "- retourne uniquement un CoachDecision JSON valide; aucune prose hors JSON\n"
        "- les resultats tools sont la source de verite pour ids, dates, seances, facts et validations\n"
        "- la derniere reponse de la phase tool est un brouillon non fiable; utilise-la seulement comme indice d'intention\n"
        "- ignore tout markup provider/tool-call visible dans la derniere reponse\n"
        "- si un tool draft_* retourne payload.patch et que l'utilisateur demande une mutation planning, copie ce patch dans plan_patch\n"
        "- si un patch significatif est valide mais risque, utilise response_type=\"requires_confirmation\" avec plan_patch\n"
        "- si aucune action structuree fiable n'existe, retourne response_type=\"no_change\" ou une clarification courte\n"
        "- ne dis jamais qu'un changement est applique sans action structuree valide\n"
        "- preserve les memory_actions, execution_actions et pending_resolution seulement si le contexte les justifie\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n\n"
        "RESULTATS_TOOLS:\n"
        f"{tool_result_summary}\n\n"
        "DERNIERE_REPONSE_PHASE_TOOL:\n"
        f"{raw_block}\n\n"
        "Retourne uniquement le JSON."
    )
    try:
        data = request_structured_json_fn(
            system=system,
            messages=[{"role": "user", "content": compiler_prompt}],
            model=model,
            max_tokens=max(max_tokens, 1400),
        )
    except Exception as exc:
        logger.warning("llm.tool_decision_compiler_failed error=%s", exc)
        return None
    return legacy_parser.downgrade_free_confirmation_payload(data)


def retry_tool_followup_json_format(
    *,
    system: str,
    messages: list[dict[str, Any]],
    response: Any,
    model: str,
    max_tokens: int,
    request_message_fn: Callable[..., Any | None],
    tool_thinking_kwargs_fn: Callable[[], dict[str, Any]],
) -> Any | None:
    raw_text = gw.message_text(response)
    if not raw_text:
        return None
    retry_messages = list(messages)
    retry_messages.append({"role": "assistant", "content": gw.serialize_content_blocks(getattr(response, "content", []))})
    retry_messages.append(
        {
            "role": "user",
            "content": (
                "Ta derniere reponse a un format incorrect: ce n'est pas un JSON FitMAS valide. "
                "Les tools sont termines pour ce tour; n'appelle aucun tool supplementaire. "
                "Garde exactement la meme intention et les memes faits, mais retourne uniquement "
                "un CoachDecision JSON valide. Pas de prose hors JSON. N'invente aucun id, aucune seance, aucun commit."
            ),
        }
    )
    return request_message_fn(
        system=system,
        messages=retry_messages,
        model=model,
        max_tokens=max_tokens,
        **tool_thinking_kwargs_fn(),
    )


def tool_result_blocks(tool_use_blocks: list[Any], tool_executions: list[Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for tool_use_block, execution in zip(tool_use_blocks, tool_executions):
        result = execution.result
        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": getattr(tool_use_block, "id", ""),
                "content": json.dumps(
                    {
                        "summary": result.summary,
                        "payload": result.payload,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                ),
                "is_error": result.status != "ok",
            }
        )
    return blocks


def tool_followup_content(tool_use_blocks: list[Any], tool_executions: list[Any]) -> list[dict[str, Any]]:
    return [
        *tool_result_blocks(tool_use_blocks, tool_executions),
        {
            "type": "text",
            "text": (
                "Tu peux appeler d'autres tools si une information manque. "
                "Si un tool retourne une validation de patch, ne dis jamais que c'est applique; "
                "retourne un CoachDecision response_type=plan_patch ou requires_confirmation avec le PlanPatch voulu. "
                "Ne lance pas de review sportive longue dans ce tour; le backend re-run la gate avant tout write. "
                "Si tu as assez d'information, retourne maintenant uniquement un JSON FitMAS CoachDecision valide; "
                "pas de prose hors JSON."
            ),
        },
    ]


def tool_execution_names(tool_executions: list[Any]) -> str | None:
    names = [execution.result.tool_name for execution in tool_executions if execution.result.tool_name]
    return ",".join(names) if names else None


def any_tool_called(tool_executions: list[Any]) -> bool:
    return any(execution.trace.tool_called for execution in tool_executions)


def all_executed_tools_ok(tool_executions: list[Any]) -> bool:
    called = [execution for execution in tool_executions if execution.trace.tool_called]
    return bool(called) and all(execution.result.status == "ok" for execution in called)


def all_tool_results_ok(tool_executions: list[Any]) -> bool:
    return bool(tool_executions) and all(execution.result.status == "ok" for execution in tool_executions)


def sum_tool_latency(tool_executions: list[Any]) -> int | None:
    values = [execution.trace.tool_latency_ms for execution in tool_executions if execution.trace.tool_latency_ms is not None]
    return sum(values) if values else None


def tool_errors(tool_executions: list[Any]) -> str | None:
    errors = [execution.result.error for execution in tool_executions if execution.result.error]
    return "; ".join(errors) if errors else None


def sum_optional_ints(values: list[int | None]) -> int | None:
    present = [int(value) for value in values if value is not None]
    return sum(present) if present else None


def tool_use_blocks_from_response(response: Any) -> list[Any]:
    return [
        block
        for block in (getattr(response, "content", []) or [])
        if getattr(block, "type", None) == "tool_use"
    ]


def log_tool_session_trace(
    *,
    pipeline: str,
    tool_offered: bool,
    tool_requested: bool,
    tool_called: bool,
    tool_success: bool,
    log_tool_trace_fn: Callable[..., None],
    context_policy: str | None = None,
    tool_name: str | None = None,
    tool_latency_ms: int | None = None,
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
) -> None:
    trace = build_tool_trace(
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
    )
    log_tool_trace_fn(trace)
