from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

from pydantic import BaseModel
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.fact_memory import normalize_fact_payload as normalize_fact_memory_payload
from fitmas.fact_memory import select_relevant_facts
from fitmas.time_context import build_time_context, render_time_context
from fitmas.tool_contract import ToolCall, ToolContext
from fitmas.tool_metrics import build_tool_trace, log_tool_trace
from fitmas.tool_registry import list_tools_for_pipeline
from fitmas.tool_routing import route_tools_for_query
from fitmas.tool_runtime import execute_tool_call

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
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "no_change"
    target_session_id: int | None = None
    second_session_id: int | None = None
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
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
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def _request_text(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512) -> str | None:
    response = _request_message(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
    )
    return _message_text(response)


def _request_message(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
):
    client = _client()
    if not client:
        return None
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        return client.messages.create(**kwargs)
    except Exception:
        logger.exception("LLM message call failed")
        return None


def _request_json(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> dict | None:
    raw = _request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to decode LLM JSON: %s", raw[:200])
        return None


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
    time_block = render_time_context(resolved_time_context)
    routing = route_tools_for_query(user_text, pipeline=tool_context.pipeline) if tool_context is not None else None
    prompt_policy = select_conversation_prompt_policy(routing_reason=routing.reason if routing is not None else None)

    # Build conversation context
    history_block = ""
    history_messages_used = 0
    if conversation_history:
        recent = conversation_history[-prompt_policy.history_limit :]
        history_messages_used = len(recent)
        lines = []
        for msg in recent:
            prefix = "Utilisateur" if msg["role"] == "user" else "FitMAS"
            lines.append(f"{prefix}: {msg['text']}")
        if lines:
            history_block = f"\nHistorique recent:\n" + "\n".join(lines) + "\n"

    coach_block = ""
    if coach_context and prompt_policy.include_coach_context:
        coach_block = (
            "\nContexte coach:\n"
            f"- nom: {coach_context.get('coach_name', 'FitMAS')}\n"
            f"- style: {coach_context.get('coach_style', 'direct')}\n"
            f"- relation: {coach_context.get('coach_relationship', '')}\n"
            f"- fait bien: {coach_context.get('coach_do', '')}\n"
            f"- ne fait jamais: {coach_context.get('coach_dont', '')}\n"
            f"- ame: {coach_context.get('coach_soul', '')}\n"
            f"- session du jour id: {coach_context.get('today_session_id')}\n"
        )

    facts_block = ""
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts(remembered_facts or [])
    if selected_facts and prompt_policy.include_facts:
        facts_block = "\nMemoire utile:\n" + "\n".join(f"- {fact}" for fact in selected_facts) + "\n"

    timeline_block = ""
    if timeline_summary and prompt_policy.include_timeline:
        timeline_block = f"\nCalendrier date reel:\n{timeline_summary}\n"

    execution_block = ""
    if execution_summary and prompt_policy.include_execution:
        execution_block = f"\n{execution_summary}\n"

    temporal_block = ""
    if temporal_summary and prompt_policy.include_temporal:
        temporal_block = f"\n{temporal_summary}\n"

    claim_block = ""
    if activity_claim_summary and prompt_policy.include_claim:
        claim_block = f"\n{activity_claim_summary}\n"

    signal_block = ""
    if signal_summary and prompt_policy.include_signals:
        signal_block = f"\n{signal_summary}\n"

    plan_anchor = ""
    if prompt_policy.include_plan_summary:
        plan_anchor = f"Repere legacy semaine courante:\n{plan_summary}\n"

    prompt = f"""{time_block}
Source de vérité planning conversationnelle: calendrier daté / app.
Ignore tout repère hebdo legacy si le calendrier daté dit autre chose.
{plan_anchor}
{timeline_block}
{execution_block}{temporal_block}{claim_block}{signal_block}
{coach_block}{facts_block}
{history_block}
Nouveau message de l'utilisateur:
{user_text}

Analyse ce message et decide quelle action prendre sur le calendrier d'entrainement reel.

Actions possibles:
- "move_session": deplacer une seance concrete a une date cible
- "swap_sessions": echanger deux seances concretes
- "lighten_day": alleger une seance concrete ou un jour
- "update_session": modifier le titre ou l'objectif d'une seance concrete
- "no_change": aucune modification necessaire

Les jours doivent etre en anglais: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
Quand une seance concrete est identifiable dans le calendrier date reel, privilegie toujours `target_session_id`.
Pour un echange concret, renseigne `target_session_id` et `second_session_id`.
Pour un deplacement concret, renseigne `target_date` au format ISO `YYYY-MM-DD`.
Si l'utilisateur parle de aujourd'hui, demain, hier, ce soir, demain matin ou demande la date/l'heure/jour exact, tu dois raisonner a partir du contexte temporel exact ci-dessus.
Tu dois respecter cette hierarchie de verite:
1. activite reelle persistée
2. claim activite recent utilisateur
3. correction utilisateur recente dans l'historique
4. seance planifiee
5. inference faible
N'affirme jamais une duree ou un sport comme un fait si cela vient seulement du plan et qu'un claim utilisateur plus recent dit autre chose.
Si une activite reelle existe aujourd'hui mais sur un autre sport que le plan, ne dis jamais "tu n'as rien fait". Le bon diagnostic est "hors plan" ou "pas la seance prevue".
Si la bonne reponse est purement temporelle ou explicative, garde "mutation_type": "no_change" et reponds clairement dans "fitmas_message".

Exemples:
- "mardi c'est mort, je bascule sur jeudi" → move_session, target_session_id: 12, target_date: "2026-03-26"
- "mercredi j'ai une grosse journee" → lighten_day, target_session_id: 12
- "echange samedi et dimanche" → swap_sessions, target_session_id: 12, second_session_id: 13
- "jeudi je prefere faire du fractionne" → update_session, target_session_id: 12, new_title: "Fractionne 8x400m"
- "ok ca me va" → no_change
- "on est quel jour exactement ?" → no_change, fitmas_message explique le jour et la date locale
- "ce soir c'est quoi deja ?" → no_change ou update utile selon la seance du jour et le contexte temporel
- "c'est pas ce qui est sur mon planning dans l'app" → no_change, tu reconnais que l'app / calendrier date est la source de verite et tu repars de cette seance-la

Reponds avec un JSON valide contenant exactement ces champs:
- "mutation_type": une des valeurs ci-dessus
- "target_session_id": id de la seance cible ou null
- "second_session_id": id de la 2e seance si swap, sinon null
- "target_date": date cible ISO `YYYY-MM-DD` ou null
- "from_day": jour source (anglais) ou null
- "to_day": jour destination (anglais) ou null
- "new_title": nouveau titre de seance si update_session, null sinon
- "new_goal": nouvel objectif si update_session, null sinon
- "rationale": explication courte (1 phrase, pour les notes de changement)
- "fitmas_message": message a envoyer a l'utilisateur — court, direct, ancre dans le contexte

Reponds UNIQUEMENT avec le JSON, sans markdown, sans texte autour."""

    try:
        data = None
        if tool_context is not None and routing and routing.tool_names:
            data = _request_json_with_tools(
                system=_SOUL,
                prompt=prompt,
                tool_context=tool_context,
                tool_names=routing.tool_names,
                context_policy=prompt_policy.name,
                history_messages_used=history_messages_used,
            )
        if data is None:
            data = _request_json(system=_SOUL, prompt=prompt)
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


def _message_text(response: Any) -> str | None:
    if response is None:
        return None
    texts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = str(getattr(block, "text", "")).strip()
            if text:
                texts.append(text)
    if not texts:
        return None
    return "\n".join(texts).strip()


def _message_json(response: Any) -> dict | None:
    raw = _message_text(response)
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to decode LLM JSON: %s", raw[:200])
        return None


def _first_tool_use_block(response: Any) -> Any | None:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            return block
    return None


def _serialize_content_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            serialized.append({"type": "text", "text": getattr(block, "text", "")})
        elif block_type == "tool_use":
            serialized.append(
                {
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": dict(getattr(block, "input", {}) or {}),
                }
            )
    return serialized


def _usage_value(response: Any, key: str) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    value = getattr(usage, key, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sum_ints(*values: int | None) -> int | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


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
    prompt = f"""{render_time_context(resolved_time_context)}
Contexte user:
- objectif: {context['primary_objective']}
- sports: {", ".join(context['sports'])}
- style: {context['coach_style']}
- relation voulue: {context['coach_relationship']}
- ce que le coach doit faire: {context['coach_do']}
- ce qu'il ne doit jamais faire: {context['coach_dont']}
- ame libre: {context['coach_soul']}

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
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois rediger le recap final d'un onboarding.

Contexte:
- sports: {", ".join(context['sports'])}
- objectif: {context['primary_objective']}
- realite de semaine: {context['weekly_structure_notes']}
- contraintes: {" ; ".join(context['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(context['preferences']) or "aucune precisee"}
- coach: {context['coach_name']} / style {context['coach_style']}
- ame: {context['coach_soul']}

Ecris un recap court en 4 a 6 lignes:
- ce que FitMAS a compris
- les arbitrages les plus probables
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

    data = _request_json(system=_COACH_SOUL, prompt=prompt, model="claude-sonnet-4-20250514", max_tokens=3000)
    if data:
        try:
            return _merge_week_enrichment(planner_output, data)
        except Exception:
            logger.exception("Failed to merge enriched week plan")
    return _fallback_week_plan(planner_output, coach_profile)


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
        merged_days.append(
            {
                **day,
                "session_title": enriched_title if enriched_title else day["session_title"],
                "session_goal": enriched_goal if enriched_goal else day["session_goal"],
                "session_note": str(payload.get("session_note") or day["session_note"]).strip(),
                "session_description": enriched_description if enriched_description else day.get("session_description", ""),
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
    coach_name = context["coach_name"]
    return [
        f"{coach_name} est la. Mardi a l'air fragile. Je prefere garder de l'air plutot que forcer un faux bloc.",
        f"Je te construis une semaine tenable. Si mardi bouge, je garde la structure et je deplace intelligemment.",
        f"Je veux une semaine qui te ressemble, pas une semaine parfaite sur le papier. On pose les bons reperes et on garde du jeu.",
    ]


def _fallback_recap(context: dict) -> str:
    sports = ", ".join(context["sports"])
    constraints = ", ".join(context["constraints"][:3]) or "pas de contrainte forte explicite"
    return (
        f"Voila ce que j'ai retenu pour commencer.\n"
        f"Tu veux avancer sur {context['primary_objective']} avec une semaine ou {sports} doivent cohabiter proprement.\n"
        f"Je garde en tete: {constraints}.\n"
        f"Le coach va parler en mode {context['coach_style']}, avec une voix plus humaine que robotique, et il evitera {context['coach_dont'] or 'les phrases vides'}."
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

Retourne un JSON: {{"facts": [...]}}

Chaque fact:
- category: "preference" | "constraint" | "pattern" | "coaching" | "fatigue" | "availability" | "health" | "goal" | "objective"
- key: slug court
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
