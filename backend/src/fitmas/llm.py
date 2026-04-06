from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from pydantic import BaseModel
from fitmas import llm_gateway as gw
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.fact_memory import normalize_fact_payload as normalize_fact_memory_payload
from fitmas.fact_memory import select_relevant_facts
from fitmas.knowledge import load_sport_knowledge
from fitmas.llm_prompt_builder import build_layered_conversation_prompt, render_conversation_time_block
from fitmas.onboarding_contract import build_coach_profile, build_goal_summary
from fitmas.profile_summary import build_profile_summary
from fitmas.time_context import build_time_context, render_time_context
from fitmas.tools.contract import ToolCall, ToolContext
from fitmas.tools.metrics import build_tool_trace, log_tool_trace
from fitmas.tools.registry import list_tools_for_pipeline
from fitmas.tools.routing import route_tools_for_query
from fitmas.tools.runtime import execute_tool_call

logger = logging.getLogger(__name__)

_SOUL = """\
Tu es FitMAS, un coach multisport IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.\
"""

_COACH_SOUL = """\
Tu incarnes le coach personnel de FitMAS.
Tu ecris en francais.
Tu es humain, lucide, calme, precis.
Tu ne sonnes jamais comme un template, jamais comme une pub, jamais comme un bot.
Tu aides a construire une relation de coaching credible des la premiere interaction.\
"""


class MutationDecision(BaseModel):
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "replace_session" | "no_change"
    target_session_id: int | None = None
    second_session_id: int | None = None
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None
    rationale: str            # 1 phrase, pour les change notes
    fitmas_message: str       # message envoye a l'utilisateur


_DAYS_FR_TO_EN = {
    "lundi": "monday", "mardi": "tuesday", "mercredi": "wednesday",
    "jeudi": "thursday", "vendredi": "friday", "samedi": "saturday",
    "dimanche": "sunday",
}


def _normalize_day(raw: str | None) -> str | None:
    """Convert French day names to English keys, pass through English names."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def _client():
    return gw.client()


def _request_text(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512) -> str | None:
    """Request text — routes through module-level _request_message (patchable by tests)."""
    response = _request_message(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
    )
    return _message_text(response)


def _request_message(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
):
    """Send message — delegates to gateway. Tests monkey-patch this function."""
    return gw.request_message(
        system=system, messages=messages, model=model, max_tokens=max_tokens,
        tools=tools, tool_choice=tool_choice,
    )


def _request_json(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> dict | None:
    """Request JSON — routes through module-level _request_text (patchable chain)."""
    raw = _request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    cleaned = _strip_json_fences(raw)
    for candidate in _json_parse_candidates(cleaned):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    logger.exception("Failed to decode LLM JSON: %s", cleaned[:200])
    return None


def _strip_json_fences(raw: str) -> str:
    candidate = raw.strip()
    if candidate.startswith("```"):
        parts = candidate.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
    if candidate.startswith("json"):
        candidate = candidate[4:]
    return candidate.strip()


def _json_parse_candidates(raw: str) -> list[str]:
    candidates: list[str] = []
    started = _slice_from_json_start(raw)
    for candidate in (
        raw.strip(),
        started,
        _balanced_json_prefix(started),
        _repair_truncated_json(started),
    ):
        normalized = str(candidate or "").strip()
        if not normalized or normalized in candidates:
            continue
        candidates.append(normalized)
    return candidates


def _slice_from_json_start(raw: str) -> str:
    start_positions = [pos for pos in (raw.find("{"), raw.find("[")) if pos >= 0]
    if not start_positions:
        return raw
    return raw[min(start_positions):].strip()


def _balanced_json_prefix(raw: str) -> str | None:
    if not raw:
        return None
    stack: list[str] = []
    in_string = False
    escape = False
    started = False
    for idx, char in enumerate(raw):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
            started = True
            continue
        if char in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener, char) not in {("{", "}"), ("[", "]")}:
                return None
            if started and not stack:
                return raw[: idx + 1]
    return None


def _repair_truncated_json(raw: str) -> str | None:
    if not raw:
        return None
    buffer: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False
    for char in raw:
        buffer.append(char)
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
            continue
        if char in "}]":
            if stack and (stack[-1], char) in {("{", "}"), ("[", "]")}:
                stack.pop()
    repaired = "".join(buffer).rstrip()
    if in_string:
        repaired += '"'
    if stack:
        repaired += "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return repaired.strip()


def decide(
    user_text: str,
    plan_summary: str,
    timeline_summary: str | None = None,
    execution_summary: str | None = None,
    temporal_summary: str | None = None,
    activity_claim_summary: str | None = None,
    signal_summary: str | None = None,
    conversation_history: list[dict] | None = None,
    coach_context: dict | None = None,
    remembered_facts: list[dict] | None = None,
    time_context: dict | None = None,
    tool_context: ToolContext | None = None,
) -> MutationDecision | None:
    """
    Call the LLM to extract intent and decide a plan mutation.
    Returns None if LLM is unavailable (API key missing or error) -- caller falls back to rules.
    """
    if not _client():
        logger.info("No Anthropic client available — falling back to rules")
        return None

    resolved_time_context = time_context or build_time_context((coach_context or {}).get("timezone"))
    routing = route_tools_for_query(user_text, pipeline=tool_context.pipeline) if tool_context is not None else None
    prompt_policy = select_conversation_prompt_policy(
        routing_reason=routing.reason if routing is not None else None,
        intent=routing.intent if routing is not None else None,
    )
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts(remembered_facts or [])
    prompt_bundle = build_layered_conversation_prompt(
        user_text=user_text,
        prompt_policy=prompt_policy,
        time_block=render_conversation_time_block(resolved_time_context),
        profile_summary=(coach_context or {}).get("profile_summary") or build_profile_summary(remembered_facts or []),
        plan_summary=plan_summary,
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=conversation_history,
        coach_context=coach_context,
        selected_facts=selected_facts,
    )
    prompt = prompt_bundle.prompt
    history_messages_used = prompt_bundle.history_messages_used
    system_prompt = prompt_bundle.system

    try:
        data = None
        if tool_context is not None and routing and routing.tool_names:
            data = _request_json_with_tools(
                system=system_prompt,
                prompt=prompt,
                tool_context=tool_context,
                tool_names=routing.tool_names,
                context_policy=prompt_policy.name,
                history_messages_used=history_messages_used,
            )
        if data is None:
            data = _request_json(system=system_prompt, prompt=prompt)
        if not data:
            return None

        # Normalize French day names to English
        data["from_day"] = _normalize_day(data.get("from_day"))
        data["to_day"] = _normalize_day(data.get("to_day"))

        decision = MutationDecision(**data)
        logger.info(
            "LLM decision: %s (session=%s, session2=%s, from=%s, to=%s, date=%s) — %s",
            decision.mutation_type, decision.target_session_id, decision.second_session_id, decision.from_day, decision.to_day, decision.target_date,
            decision.rationale,
        )
        return decision

    except Exception:
        logger.exception("LLM call failed — falling back to rules")
        return None


def _request_json_with_tools(
    *,
    system: str,
    prompt: str,
    tool_context: ToolContext,
    tool_names: tuple[str, ...],
    context_policy: str,
    history_messages_used: int,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
) -> dict | None:
    tools = list_tools_for_pipeline(tool_context.pipeline, tool_names=tool_names)
    if not tools:
        return None
    started_at = perf_counter()
    prompt_char_count = len(prompt)
    tool_count_offered = len(tools)
    initial_messages = [{"role": "user", "content": prompt}]
    response = _request_message(
        system=system,
        messages=initial_messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
    )
    if response is None:
        _log_tool_session_trace(
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
            total_duration_ms=_elapsed_ms(started_at),
            response_stop_reason="initial_request_failed",
        )
        return None
    initial_stop_reason = str(getattr(response, "stop_reason", "") or "")
    initial_prompt_tokens = _usage_value(response, "input_tokens")
    initial_response_tokens = _usage_value(response, "output_tokens")
    if initial_stop_reason != "tool_use":
        data = _message_json(response)
        _log_tool_session_trace(
            pipeline=tool_context.pipeline,
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=False,
            tool_called=False,
            tool_success=data is not None,
            fallback_used=data is None,
            llm_round_trips=1,
            tool_count_offered=tool_count_offered,
            history_messages_used=history_messages_used,
            prompt_char_count=prompt_char_count,
            prompt_tokens_estimate=initial_prompt_tokens,
            response_tokens_estimate=initial_response_tokens,
            total_duration_ms=_elapsed_ms(started_at),
            response_stop_reason=initial_stop_reason or "end_turn",
        )
        return data

    tool_use_block = _first_tool_use_block(response)
    if tool_use_block is None:
        data = _message_json(response)
        _log_tool_session_trace(
            pipeline=tool_context.pipeline,
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=True,
            tool_called=False,
            tool_success=data is not None,
            tool_error="tool_use stop_reason without tool block",
            fallback_used=True,
            llm_round_trips=1,
            tool_count_offered=tool_count_offered,
            history_messages_used=history_messages_used,
            prompt_char_count=prompt_char_count,
            prompt_tokens_estimate=initial_prompt_tokens,
            response_tokens_estimate=initial_response_tokens,
            total_duration_ms=_elapsed_ms(started_at),
            response_stop_reason=initial_stop_reason or "tool_use",
        )
        return data

    tool_result, tool_trace = execute_tool_call(
        ToolCall(tool_name=str(getattr(tool_use_block, "name", "")), arguments=dict(getattr(tool_use_block, "input", {}) or {})),
        context=tool_context,
        llm_round_trips=2,
        prompt_tokens_estimate=initial_prompt_tokens,
        response_tokens_estimate=initial_response_tokens,
    )
    followup_messages = list(initial_messages)
    followup_messages.append({"role": "assistant", "content": _serialize_content_blocks(getattr(response, "content", []))})
    followup_messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": getattr(tool_use_block, "id", ""),
                    "content": json.dumps(
                        {
                            "summary": tool_result.summary,
                            "payload": tool_result.payload,
                            "error": tool_result.error,
                        },
                        ensure_ascii=False,
                    ),
                    "is_error": tool_result.status != "ok",
                }
            ],
        }
    )
    final_response = _request_message(
        system=system,
        messages=followup_messages,
        model=model,
        max_tokens=max_tokens,
    )
    if final_response is None:
        _log_tool_session_trace(
            pipeline=tool_context.pipeline,
            tool_name=tool_result.tool_name,
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=True,
            tool_called=tool_trace.tool_called,
            tool_latency_ms=tool_trace.tool_latency_ms,
            tool_success=tool_trace.tool_success,
            tool_error=tool_result.error or "tool followup request failed",
            fallback_used=True,
            llm_round_trips=2,
            tool_count_offered=tool_count_offered,
            history_messages_used=history_messages_used,
            prompt_char_count=prompt_char_count,
            prompt_tokens_estimate=initial_prompt_tokens,
            response_tokens_estimate=initial_response_tokens,
            total_duration_ms=_elapsed_ms(started_at),
            response_stop_reason="followup_request_failed",
        )
        return None
    final_stop_reason = str(getattr(final_response, "stop_reason", "") or "")
    final_prompt_tokens = _usage_value(final_response, "input_tokens")
    final_response_tokens = _usage_value(final_response, "output_tokens")
    data = _message_json(final_response)
    _log_tool_session_trace(
        pipeline=tool_context.pipeline,
        tool_name=tool_result.tool_name,
        tool_offered=True,
        context_policy=context_policy,
        tool_requested=True,
        tool_called=tool_trace.tool_called,
        tool_latency_ms=tool_trace.tool_latency_ms,
        tool_success=tool_trace.tool_success and data is not None,
        tool_error=tool_result.error if data is not None else (tool_result.error or "tool followup response was not valid JSON"),
        fallback_used=data is None,
        llm_round_trips=2,
        tool_count_offered=tool_count_offered,
        history_messages_used=history_messages_used,
        prompt_char_count=prompt_char_count,
        prompt_tokens_estimate=_sum_ints(initial_prompt_tokens, final_prompt_tokens),
        response_tokens_estimate=_sum_ints(initial_response_tokens, final_response_tokens),
        total_duration_ms=_elapsed_ms(started_at),
        response_stop_reason=final_stop_reason or "end_turn",
    )
    return data


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(
            f"- {d.label} ({d.day}): [{getattr(d, 'sport_type', 'running')}] {d.session_title} — {d.session_goal} "
            f"(priorite: {d.priority}, flexibilite: {d.flexibility})"
        )
    return "\n".join(lines)


_message_text = gw.message_text
_message_json = gw.message_json
_first_tool_use_block = gw.first_tool_use_block
_serialize_content_blocks = gw.serialize_content_blocks
_usage_value = gw.usage_value
_sum_ints = gw.sum_ints
_elapsed_ms = gw.elapsed_ms


def _log_tool_session_trace(
    *,
    pipeline: str,
    tool_offered: bool,
    tool_requested: bool,
    tool_called: bool,
    tool_success: bool,
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
    log_tool_trace(trace)
def make_timeline_summary(sessions: list) -> str:
    lines = []
    for session in sessions:
        day = getattr(session, "day", "")
        date_value = getattr(session, "scheduled_date", "")
        lines.append(
            f"- id={getattr(session, 'id', '?')} | date={date_value} | day={day} | "
            f"[{getattr(session, 'sport_type', 'running')}] {getattr(session, 'session_title', '')} "
            f"| goal={getattr(session, 'session_goal', '')} | status={getattr(session, 'completion_status', 'planned')}"
        )
    return "\n".join(lines)


def preview_coach_voice(context: dict, *, time_context: dict | None = None) -> list[str]:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Contexte user:
- cap: {build_goal_summary(context)}
- sports: {", ".join(context['sports'])}
- realite de semaine: {context.get('weekly_structure_notes', '')}
- etat actuel: {context.get('current_state_notes', '') or 'encore en cours de calibration'}
- preset: {coach['coach_preset_label']}
- style: {coach['coach_style']}
- relation voulue: {coach['coach_relationship']}
- ce que le coach doit faire: {coach['coach_do']}
- ce qu'il ne doit jamais faire: {coach['coach_dont']}
- ame libre: {coach['coach_soul']}

Genere exactement 3 messages courts que ce coach pourrait envoyer.
Scenario:
- la semaine vient d'etre comprise
- mardi parait fragile
- il faut montrer de la presence sans surjouer

Contraintes:
- 1 ou 2 phrases max par message
- chaque proposition doit avoir une saveur differente mais rester dans la meme ame
- pas de compliment generique
- reponds en JSON: {{"messages": ["...", "...", "..."]}}"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=700)
    if data and isinstance(data.get("messages"), list) and len(data["messages"]) >= 3:
        return [str(message).strip() for message in data["messages"][:3]]

    return _fallback_voice_preview(context)


def formulate_onboarding_recap(context: dict, *, time_context: dict | None = None) -> str:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois rediger le recap final d'un onboarding.

Contexte:
- sports: {", ".join(context['sports'])}
- cap: {build_goal_summary(context)}
- realite de semaine: {context['weekly_structure_notes']}
- etat actuel: {context.get('current_state_notes', '') or 'encore a lire sur les premieres semaines'}
- contraintes: {" ; ".join(context['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(context['preferences']) or "aucune precisee"}
- coach: {coach['coach_name']} / preset {coach['coach_preset_label']} / style {coach['coach_style']}
- ame: {coach['coach_soul']}

Ecris un recap court en 4 a 6 lignes:
- ce que FitMAS a compris
- ce que tu protegeras des le debut
- ce qui reste encore a clarifier si besoin
- le ton du coach

Pas de markdown complexe. Pas de phrase creuse."""

    text = _request_text(system=_COACH_SOUL, prompt=prompt, max_tokens=320)
    if text:
        return text
    return _fallback_recap(context)


def formulate_week_plan(
    planner_output: dict,
    user_profile: dict,
    coach_profile: dict,
    *,
    time_context: dict | None = None,
) -> dict:
    resolved_time_context = time_context or build_time_context(user_profile.get("timezone") or coach_profile.get("timezone"))
    sports_set = set(user_profile.get("sports", []))
    knowledge_block = load_sport_knowledge(sports_set, max_tokens=1500)
    planning_context = planner_output.get("planning_context") or {}
    planning_context_block = ""
    if planning_context:
        planning_context_block = (
            "\nDecision de planning deja prise hors LLM:\n"
            f"- planning_mode: {planning_context.get('planning_mode')}\n"
            f"- weekly_target_tss: {planning_context.get('weekly_target_tss')}\n"
            f"- key_session_count: {planning_context.get('key_session_count')}\n"
            f"- strength_session_count: {planning_context.get('strength_session_count')}\n"
            f"- long_session: {planning_context.get('long_session')}\n"
            f"- rationale: {' ; '.join(planning_context.get('rationale') or [])}\n"
            f"- adaptations: {' ; '.join(planning_context.get('adaptations') or [])}\n"
        )
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois enrichir un squelette de semaine multisport pour que chaque seance soit directement utilisable en situation reelle.

User:
- objectif: {user_profile['primary_objective']}
- sports: {", ".join(user_profile['sports'])}
- realite de semaine: {user_profile['weekly_structure_notes']}
- contraintes: {" ; ".join(user_profile['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(user_profile['preferences']) or "aucune precisee"}

Coach:
- nom: {coach_profile['coach_name']}
- style: {coach_profile['coach_style']}
- relation: {coach_profile['coach_relationship']}
- fait: {coach_profile['coach_do']}
- ne fait jamais: {coach_profile['coach_dont']}
- ame: {coach_profile['coach_soul']}
{planning_context_block}

Connaissances sport (utilise comme reference pour formuler les seances):
{knowledge_block}

Squelette:
{json.dumps(planner_output, ensure_ascii=False)}

Retourne un JSON avec:
- intention
- summary
- days: liste de 7 objets dans le meme ordre

Chaque day doit contenir:
- day
- session_title: titre court et precis (ex: "Footing endurance 45min zone 2", "Fractionne 8x400m R1min", "Natation technique 4x200m")
- session_goal: objectif clair en 1 phrase actionnable
- session_description: le deroulement complet de la seance, structure en blocs. C'est le champ le plus important.
- session_note: note de contexte sur la place de la seance dans la semaine (1-2 phrases)
- watch_title
- watch_detail

REGLE CRITIQUE — session_description:
Chaque session_description doit etre un plan de seance concret que l'utilisateur peut suivre tel quel.
Format: blocs separes par des retours a la ligne, avec durees/distances/intensites.

Exemples par sport:
- Running easy: "Echauffement 10min marche/trot\\n30min footing zone 2 (allure confortable, on peut parler)\\n5min retour au calme marche"
- Running quality: "Echauffement 15min footing progressif\\n8x400m a allure 10k, recup 1min trot\\n10min retour au calme footing lent"
- Running long: "10min trot lent\\n55min footing endurance zone 2 (regulier, pas d'acceleration)\\n5min marche retour calme\\nObjectif: finir frais, pas vide"
- Natation technique: "200m echauffement nage libre souple\\n4x100m crawl technique (rattrapé, poings fermés, amplitude) R20s\\n4x50m sprint 80% R30s\\n200m retour calme dos/brasse"
- Natation easy: "200m echauffement varié (crawl/dos)\\n8x50m crawl allure reguliere R15s\\n4x25m au choix\\n100m souple retour calme"
- Velo endurance: "15min echauffement progressif\\n50min zone 2 cadence 85-95rpm\\n10min retour calme moulinette"
- Escalade bloc: "15min echauffement articulaire + dalle facile\\n45min blocs projet (3-4 essais par bloc, repos complet entre)\\n20min volume facile\\n10min etirements"
- Renfo/strength: "Echauffement 5min mobilite\\n3x12 squats + 3x10 pompes + 3x30s gainage\\n2x15 fentes + 2x10 rowing\\nEtirements 5min"
- Repos: pas de session_description (laisser vide)

Adapte les distances, allures et series au niveau de l'utilisateur et a la duree prevue dans le squelette.
Ne mets JAMAIS de description vague comme "Fais ta seance normalement" ou "Seance de natation classique".

Regles:
- ne change jamais sport_type, session_type, duration_min, intensity, load_score, priority, flexibility
- ancre la voix dans le coach
- pas de phrases generiques
- session_title doit etre plus precis que le squelette (ajouter volume, allure, format)
- session_goal doit dire ce que la seance construit concretement
- session_description est le coeur: plan de seance structuré, blocs clairs, actionnable immediatement"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, model="claude-sonnet-4-6", max_tokens=3000)
    if data:
        try:
            return _merge_week_enrichment(planner_output, data)
        except Exception:
            logger.exception("Failed to merge enriched week plan")
    return _fallback_week_plan(planner_output, coach_profile)


def _sanitize_coach_text(text: str, fallback: str) -> str:
    """Reject LLM output that looks like a leaked prompt or instruction."""
    if not text:
        return fallback
    # Detect 3rd-person instruction patterns that shouldn't face the user
    leak_markers = (
        "l'utilisateur",
        "the user",
        "genere ",
        "génère ",
        "transforme ",
        "reponds en json",
        "réponds en json",
        "session_note",
        "session_title",
    )
    lower = text.lower()
    if any(marker in lower for marker in leak_markers):
        logger.warning("Prompt leak detected in LLM output, using fallback: %s", text[:80])
        return fallback
    return text


def _merge_week_enrichment(planner_output: dict, enrichment: dict) -> dict:
    base_days = planner_output["days"]
    enriched_days = enrichment.get("days", [])
    by_day = {day["day"]: day for day in enriched_days if isinstance(day, dict) and day.get("day")}

    merged_days = []
    for day in base_days:
        payload = by_day.get(day["day"], {})
        watch_title = payload.get("watch_title")
        watch_detail = payload.get("watch_detail")
        # Enrich title and goal only if LLM provided more specific versions
        enriched_title = str(payload.get("session_title") or "").strip()
        enriched_goal = str(payload.get("session_goal") or "").strip()
        enriched_description = str(payload.get("session_description") or "").strip()
        raw_note = str(payload.get("session_note") or day["session_note"]).strip()
        merged_days.append(
            {
                **day,
                "session_title": enriched_title if enriched_title else day["session_title"],
                "session_goal": enriched_goal if enriched_goal else day["session_goal"],
                "session_note": _sanitize_coach_text(raw_note, day["session_note"]),
                "session_description": _sanitize_coach_text(enriched_description, day.get("session_description", "")) if enriched_description else day.get("session_description", ""),
                "watch_items": [
                    (
                        str(watch_title).strip() if watch_title else day["watch_items"][0][0],
                        str(watch_detail).strip() if watch_detail else day["watch_items"][0][1],
                    )
                ],
            }
        )

    return {
        "intention": str(enrichment.get("intention") or planner_output["intention_seed"]).strip(),
        "summary": str(enrichment.get("summary") or planner_output["intention_seed"]).strip(),
        "days": merged_days,
    }


def _fallback_voice_preview(context: dict) -> list[str]:
    coach = build_coach_profile(context)
    coach_name = coach["coach_name"]
    return [
        f"{coach_name} est la. Mardi a l'air fragile. Je prefere garder de l'air plutot que forcer un faux bloc.",
        f"Je te construis une semaine tenable. Si mardi bouge, je garde la structure et je deplace intelligemment.",
        f"Je veux une semaine qui te ressemble, pas une semaine parfaite sur le papier. On pose les bons reperes et on garde du jeu.",
    ]


def _fallback_recap(context: dict) -> str:
    coach = build_coach_profile(context)
    sports = ", ".join(context["sports"])
    constraints = ", ".join(context["constraints"][:3]) or "pas de contrainte forte explicite"
    goal_summary = build_goal_summary(context) or context["primary_objective"]
    current_state = context.get("current_state_notes") or "forme recente encore a affiner"
    return (
        f"Voila ce que j'ai retenu pour commencer.\n"
        f"Tu veux avancer sur {goal_summary} avec une semaine ou {sports} doivent cohabiter proprement.\n"
        f"Etat de depart retenu: {current_state}.\n"
        f"Je garde en tete: {constraints}.\n"
        f"Je protegerai d'abord les creneaux tenables et les seances qui comptent vraiment.\n"
        f"Le coach va parler en mode {coach['coach_preset_label'].lower()}, avec une voix {coach['coach_soul']}, et il evitera {coach['coach_dont'] or 'les phrases vides'}."
    )


def _fallback_week_plan(planner_output: dict, coach_profile: dict) -> dict:
    days = []
    for day in planner_output["days"]:
        days.append(
            {
                **day,
                "session_note": _fallback_day_note(day, coach_profile),
                "session_description": day.get("session_description", ""),
                "watch_items": day["watch_items"],
            }
        )

    return {
        "intention": planner_output["intention_seed"],
        "summary": _fallback_summary(days, coach_profile["coach_name"]),
        "days": days,
    }


def _fallback_day_note(day: dict, coach_profile: dict) -> str:
    coach_name = coach_profile["coach_name"]
    if day["sport_type"] == "rest":
        return f"{coach_name} laisse de l'air ici. Mieux vaut garder de la marge que remplir pour rien."
    if day["priority"] == "Seance cle":
        return f"{coach_name} pose ce bloc ici parce qu'il doit compter sans casser le reste."
    if day["priority"] == "Repere fort":
        return f"{coach_name} garde ce repere pour lire si la semaine tient vraiment dans la vraie vie."
    return f"{coach_name} garde cette seance lisible et utile. Le but est d'empiler proprement, pas de rajouter du bruit."


def _fallback_summary(days: list[dict], coach_name: str) -> str:
    active = [day for day in days if day["sport_type"] != "rest"]
    sports = ", ".join(sorted({day["sport_type"] for day in active}))
    return f"{coach_name} pose une semaine claire entre {sports}, avec un bloc fort, un repere long, et assez d'air pour que ca reste vivable."


def extract_facts(user_text: str, assistant_text: str, existing_facts: list[dict]) -> list[dict]:
    prompt = f"""Analyse cet echange et decide s'il faut memoriser des faits utiles pour le coach.

Faits deja connus:
{json.dumps(existing_facts, ensure_ascii=False)}

Utilisateur:
{user_text}

Coach:
{assistant_text}

Tu dois extraire seulement des faits:
- stables
- personnels
- actionnables
- utiles pour les prochaines decisions

Ne memorise PAS:
- humeur passagere
- phrase vague
- details jetables
- diagnostics

Pour chaque fait, evalue sa duree de vie selon la categorie:
- Une douleur/blessure/gene = category "health", persiste plusieurs semaines
- Une fatigue passagere = category "fatigue", dure 1-2 jours seulement
- Une indispo ponctuelle = category "availability", dure 1-3 jours
- Un objectif ou preference = category "goal"/"preference", persiste longtemps
- Un claim d'activite = category "execution", ne persiste que la journee
Ne confonds pas une blessure (long terme, affecte le plan) avec une fatigue (court terme, signal du jour).

IMPORTANT: Si un fait existant couvre deja le meme sujet (meme category + meme key ou sujet proche), utilise le MEME key avec action "upsert" pour le mettre a jour. Ne cree PAS de nouveau fait avec un key different pour le meme sujet.

Retourne un JSON: {{"facts": [...]}}

Chaque fact:
- category: "preference" | "constraint" | "pattern" | "coaching" | "fatigue" | "availability" | "health" | "goal" | "objective" | "execution"
- key: slug court (reutilise le key existant si c'est une mise a jour)
- value: phrase courte utile
- confidence: float 0..1
- confirmed: bool
- source: "conversation"
- action: "upsert" | "archive"

Si rien d'utile: {{"facts": []}}"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=900)
    if data and isinstance(data.get("facts"), list):
        return [_normalize_fact_payload(fact) for fact in data["facts"] if isinstance(fact, dict)]
    return _fallback_extract_facts(user_text)


def select_prompt_facts(facts: list[dict]) -> list[str]:
    return select_relevant_facts([normalize_fact_memory_payload(fact) for fact in facts], affects=["conversation"], limit=6)


def _fallback_extract_facts(user_text: str) -> list[dict]:
    text = user_text.strip()
    lowered = text.lower()
    facts: list[dict] = []

    if any(token in lowered for token in ("prefere", "préfère", "j'aime", "j aime")):
        facts.append(
            {
                "category": "preference",
                "key": _slugify(text[:48]),
                "value": text,
                "confidence": 0.72,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    if any(day in lowered for day in ("mardi", "jeudi", "lundi", "mercredi", "vendredi", "samedi", "dimanche")) and any(
        token in lowered for token in ("fragile", "pas dispo", "indispo", "jamais", "souvent", "complique", "compliqué")
    ):
        facts.append(
            {
                "category": "constraint",
                "key": _slugify(text[:48]),
                "value": text,
                "confidence": 0.76,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    if "escalade" in lowered and any(token in lowered for token in ("lourd", "lourde", "fatigue", "crame", "cramé")):
        facts.append(
            {
                "category": "pattern",
                "key": "escalade_charge_lendemain",
                "value": text,
                "confidence": 0.7,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    return [_normalize_fact_payload(fact) for fact in facts]


def _normalize_fact_payload(fact: dict) -> dict:
    value = str(fact.get("value", "")).strip()
    key = str(fact.get("key") or _slugify(value[:48])).strip() or "fact"
    category = str(fact.get("category", "preference")).strip() or "preference"
    action = str(fact.get("action", "upsert")).strip() or "upsert"
    normalized = {
        "category": category,
        "key": key,
        "value": value,
        "confidence": float(fact.get("confidence", 0.7)),
        "confirmed": bool(fact.get("confirmed", False)),
        "source": str(fact.get("source", "conversation")).strip() or "conversation",
        "action": action,
        "active": action != "archive",
    }
    return normalize_fact_memory_payload(normalized)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:120] or "fact"
