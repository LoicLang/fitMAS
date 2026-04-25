from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from time import perf_counter
from typing import Any, Literal

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
from fitmas.tools.routing import IntentCategory, route_tools_for_query
from fitmas.tools.runtime import ToolExecution, execute_tool_calls

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
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "replace_session" | "create_session" | "no_change"
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


class CoachDecision(BaseModel):
    response_type: Literal["reply", "no_change", "mutation_decision", "plan_patch", "requires_confirmation"]
    rationale: str
    fitmas_message: str
    mutation_decision: MutationDecision | None = None
    plan_patch: Any | None = None
    confirmation_reason: str | None = None


_DAYS_FR_TO_EN = {
    "lundi": "monday", "mardi": "tuesday", "mercredi": "wednesday",
    "jeudi": "thursday", "vendredi": "friday", "samedi": "saturday",
    "dimanche": "sunday",
}

_TURN_INTENT_TO_PROMPT_INTENT = {
    "availability_constraint": IntentCategory.PLAN_NEGOTIATION,
    "plan_mutation": IntentCategory.PLAN_NEGOTIATION,
    "plan_lookup": IntentCategory.PLAN_LOOKUP,
    "execution_report": IntentCategory.EXECUTION_REPORT,
    "health_signal": IntentCategory.PLAN_NEGOTIATION,
    "preference_signal": IntentCategory.PLAN_NEGOTIATION,
}
_TURN_INTENT_TOOL_BUDGETS = {
    IntentCategory.PLAN_NEGOTIATION: (
        "get_today_context",
        "get_plan_window",
        "get_load_context",
        "get_user_constraints",
        "propose_replan",
        "get_relevant_facts",
    ),
    IntentCategory.PLAN_LOOKUP: (
        "get_today_context",
        "get_plan_window",
        "get_user_constraints",
    ),
    IntentCategory.EXECUTION_REPORT: (
        "get_today_context",
        "get_recent_activities",
    ),
}
_ALLOWED_MUTATION_TYPES = {
    "move_session",
    "lighten_day",
    "swap_sessions",
    "update_session",
    "replace_session",
    "create_session",
    "no_change",
}
_MUTATIONS_REQUIRING_TARGET_SESSION = {
    "move_session",
    "lighten_day",
    "update_session",
    "replace_session",
}
_NO_CHANGE_ACTION_CLAIM_PATTERNS = (
    "le plan sera ajuste",
    "calendrier sera ajuste",
    "planning sera ajuste",
    "sera reprogramme",
    "je vais ajuster",
    "je vais modifier",
    "je vais construire",
    "je construis",
    "je vais creer",
    "je vais devoir creer",
    "je dois creer",
    "je cree",
    "j ajoute",
    "j ajoute la seance",
    "je pose",
    "je place",
    "je modifie le plan",
    "je modifie le calendrier",
    "je deplace",
    "je libere",
    "je mets a jour",
    "j ai mis a jour",
    "a ete enregistre",
    "est enregistre",
    "est enregistree",
    "nouveau plan coherent",
    "nouvelle seance",
)
_TRUNCATED_MESSAGE_SUFFIXES = (
    "confirme que c est bien",
    "dis moi si",
    "a quelle intensite",
    "ou tu veux",
    "si tu veux",
)
_ALLOWED_COACH_RESPONSE_TYPES = {
    "reply",
    "no_change",
    "mutation_decision",
    "plan_patch",
    "requires_confirmation",
}


def _normalize_day(raw: str | None) -> str | None:
    """Convert French day names to English keys, pass through English names."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def _prompt_intent_from_turn_context(coach_context: dict | None) -> IntentCategory | None:
    primary_intent = str((coach_context or {}).get("turn_primary_intent") or "")
    return _TURN_INTENT_TO_PROMPT_INTENT.get(primary_intent)


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
    """Request JSON — routes through module-level _request_text (patchable chain).

    Delegates parsing to llm_gateway._robust_json_loads so every JSON
    entry point (this, gw.request_json, gw.message_json) shares one
    truncation/noise-repair strategy."""
    raw = _request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    return gw._robust_json_loads(raw)


def _request_structured_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
) -> dict | None:
    """Request structured JSON through the gateway, preserving test patchability.

    In local/unit contexts without DeepSeek configured, keep the old Anthropic
    path so existing tests can patch `_request_message`. With DeepSeek, use the
    gateway's structured-output path and provider fallback.
    """
    if _use_deepseek_openai_structured_output() and os.getenv("DEEPSEEK_API_KEY"):
        result = gw.request_structured_json(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )
        if result.provider_fallback_used:
            logger.info(
                "structured_json.provider_fallback provider=%s model=%s error=%s",
                result.provider,
                result.model,
                result.error,
            )
        return result.data
    if len(messages) == 1 and messages[0].get("role") == "user":
        return _request_json(system=system, prompt=str(messages[0].get("content") or ""), model=model, max_tokens=max_tokens)
    raw = _request_text(
        system=system,
        prompt="\n\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "user"),
        model=model,
        max_tokens=max_tokens,
    )
    return gw._robust_json_loads(raw or "") if raw else None


def _use_deepseek_openai_structured_output() -> bool:
    return str(os.getenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED") or "").strip().lower() in {"1", "true", "yes", "on"}


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
    turn_prompt_intent = _prompt_intent_from_turn_context(coach_context)
    effective_intent = turn_prompt_intent or (routing.intent if routing is not None else None)
    prompt_policy = select_conversation_prompt_policy(
        routing_reason=routing.reason if routing is not None else None,
        intent=effective_intent,
    )
    tool_names = (
        _TURN_INTENT_TOOL_BUDGETS.get(turn_prompt_intent, ())
        if turn_prompt_intent is not None
        else (routing.tool_names if routing is not None else ())
    )
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts(remembered_facts or [])
    unresolved_execution_followup = (coach_context or {}).get("unresolved_execution_followup")
    prompt_bundle = build_layered_conversation_prompt(
        user_text=user_text,
        prompt_policy=prompt_policy,
        time_block=render_conversation_time_block(resolved_time_context),
        profile_summary=(coach_context or {}).get("profile_summary") or build_profile_summary(remembered_facts or []),
        plan_summary=None,
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=conversation_history,
        coach_context=coach_context,
        selected_facts=selected_facts,
        unresolved_execution_followup=unresolved_execution_followup,
    )
    prompt = prompt_bundle.prompt
    history_messages_used = prompt_bundle.history_messages_used
    system_prompt = prompt_bundle.system

    try:
        _remember_invalid_decision(None)
        data = None
        if tool_context is not None and tool_names:
            data = _request_json_with_tools(
                system=system_prompt,
                prompt=prompt,
                tool_context=tool_context,
                tool_names=tool_names,
                context_policy=prompt_policy.name,
                history_messages_used=history_messages_used,
            )
        if data is None:
            data = _request_structured_json(
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
        if not data:
            return None

        # Normalize French day names to English
        data["from_day"] = _normalize_day(data.get("from_day"))
        data["to_day"] = _normalize_day(data.get("to_day"))
        data = _validate_decision_payload(data)
        if data is None:
            data = _repair_invalid_decision_payload(data=_last_invalid_decision_payload, system=system_prompt, prompt=prompt)
            data = _validate_decision_payload(data)
        if data is None:
            data = _request_claude_decision_fallback(system=system_prompt, prompt=prompt)
            data = _validate_decision_payload(data)
        if data is None:
            return None

        decision = MutationDecision(**data)
        logger.info(
            "LLM decision: %s (session=%s, session2=%s, from=%s, to=%s, date=%s) — %s",
            decision.mutation_type, decision.target_session_id, decision.second_session_id, decision.from_day, decision.to_day, decision.target_date,
            decision.rationale,
        )
        return decision

    except Exception as exc:
        error_type = _classify_llm_exception(exc)
        logger.warning(
            "llm.decide_failed type=%s message=%r — falling back to rules",
            error_type,
            str(exc)[:200],
            exc_info=True,
        )
        return None


def _validate_decision_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept only canonical FitMAS decision payloads.

    Provider JSON mode guarantees syntax, not business contract. This guard
    prevents unknown mutation labels or incomplete write decisions from reaching
    the mutation layer.
    """
    if not isinstance(data, dict):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=not_dict")
        return None
    mutation_type = str(data.get("mutation_type") or "").strip()
    if mutation_type not in _ALLOWED_MUTATION_TYPES:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=unknown_mutation_type mutation_type=%r", mutation_type)
        return None
    if not str(data.get("rationale") or "").strip():
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_rationale mutation_type=%s", mutation_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    if not fitmas_message:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type == "no_change" and _message_claims_plan_action_without_mutation(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=no_change_action_claim mutation_type=%s", mutation_type)
        return None
    if _message_violates_coach_voice(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=coach_voice_violation mutation_type=%s", mutation_type)
        return None
    if _looks_truncated_fitmas_message(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=truncated_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type in _MUTATIONS_REQUIRING_TARGET_SESSION and data.get("target_session_id") is None:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_target_session mutation_type=%s", mutation_type)
        return None
    if mutation_type == "swap_sessions" and (data.get("target_session_id") is None or data.get("second_session_id") is None):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_swap_sessions")
        return None
    if mutation_type == "create_session" and _missing_create_session_fields(data):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_create_session_fields")
        return None
    _remember_invalid_decision(None)
    return data


def parse_coach_decision_payload(data: dict[str, Any] | None) -> CoachDecision | None:
    """Validate the future coach-level decision contract.

    This is intentionally not wired into `decide()` yet. It gives the next
    PlanPatch pipeline a strict parser before the runtime starts relying on it.
    """
    if not isinstance(data, dict):
        logger.warning("llm.coach_decision_invalid reason=not_dict")
        return None
    response_type = str(data.get("response_type") or "").strip()
    if response_type not in _ALLOWED_COACH_RESPONSE_TYPES:
        logger.warning("llm.coach_decision_invalid reason=unknown_response_type response_type=%r", response_type)
        return None
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        logger.warning("llm.coach_decision_invalid reason=missing_rationale response_type=%s", response_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    if not _valid_coach_message(fitmas_message, response_type=response_type):
        return None

    payload: dict[str, Any] = {
        "response_type": response_type,
        "rationale": rationale,
        "fitmas_message": fitmas_message,
        "confirmation_reason": _optional_str(data.get("confirmation_reason")),
    }
    if response_type == "mutation_decision":
        mutation = _parse_nested_mutation_decision(data.get("mutation_decision"))
        if mutation is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_mutation_decision")
            return None
        payload["mutation_decision"] = mutation
    elif response_type == "plan_patch":
        patch = _parse_nested_plan_patch(data.get("plan_patch"))
        if patch is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_plan_patch")
            return None
        payload["plan_patch"] = patch
    elif response_type == "requires_confirmation" and not payload["confirmation_reason"]:
        logger.warning("llm.coach_decision_invalid reason=missing_confirmation_reason")
        return None
    return CoachDecision(**payload)


def _parse_nested_mutation_decision(raw: Any) -> MutationDecision | None:
    if not isinstance(raw, dict):
        return None
    validated = _validate_decision_payload(raw)
    if validated is None:
        return None
    try:
        return MutationDecision(**validated)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=mutation_model_validation_failed")
        return None


def _parse_nested_plan_patch(raw: Any) -> PlanPatch | None:
    from fitmas.plan_patch import PlanPatch

    if not isinstance(raw, dict):
        return None
    try:
        patch = PlanPatch(**raw)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=plan_patch_model_validation_failed")
        return None
    if not patch.operations:
        logger.warning("llm.coach_decision_invalid reason=empty_plan_patch")
        return None
    if not _valid_coach_message(patch.coach_message, response_type="plan_patch"):
        return None
    return patch


def _valid_coach_message(message: str, *, response_type: str) -> bool:
    if not message:
        logger.warning("llm.coach_decision_invalid reason=missing_fitmas_message response_type=%s", response_type)
        return False
    if response_type in {"reply", "no_change", "requires_confirmation"} and _message_claims_plan_action_without_mutation(message):
        logger.warning("llm.coach_decision_invalid reason=action_claim_without_patch response_type=%s", response_type)
        return False
    if _message_violates_coach_voice(message):
        logger.warning("llm.coach_decision_invalid reason=coach_voice_violation response_type=%s", response_type)
        return False
    if _looks_truncated_fitmas_message(message):
        logger.warning("llm.coach_decision_invalid reason=truncated_fitmas_message response_type=%s", response_type)
        return False
    return True


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _missing_create_session_fields(data: dict[str, Any]) -> bool:
    return (
        not str(data.get("target_date") or "").strip()
        or not str(data.get("new_sport_type") or "").strip()
        or not str(data.get("new_title") or "").strip()
        or data.get("new_duration_min") is None
    )


def _message_claims_plan_action_without_mutation(message: str) -> bool:
    normalized = _normalize_for_guard(message)
    return any(pattern in normalized for pattern in _NO_CHANGE_ACTION_CLAIM_PATTERNS)


def _looks_truncated_fitmas_message(message: str) -> bool:
    normalized = _normalize_for_guard(message).rstrip(".!?;:")
    if normalized.endswith(_TRUNCATED_MESSAGE_SUFFIXES):
        return True
    if "confirme" in normalized and message.strip()[-1:] not in {".", "!", "?"}:
        return True
    if message.strip()[-1:] not in {".", "!", "?"} and len(message.strip()) >= 40:
        return True
    return False


def _message_violates_coach_voice(message: str) -> bool:
    normalized = _normalize_for_guard(message)
    return " vos " in f" {normalized} " or " votre " in f" {normalized} "


def _normalize_for_guard(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value.lower().replace("'", " ")).strip()


_last_invalid_decision_payload: dict[str, Any] | None = None


def _remember_invalid_decision(data: dict[str, Any] | None) -> None:
    global _last_invalid_decision_payload
    _last_invalid_decision_payload = dict(data) if isinstance(data, dict) else None


def _repair_invalid_decision_payload(*, data: dict[str, Any] | None, system: str, prompt: str) -> dict | None:
    """Retry once with the invalid payload and the FitMAS decision contract."""
    if not data:
        return None
    repair_prompt = (
        "Le payload LLM suivant est invalide pour FitMAS.\n"
        "Repare-le en JSON FitMAS canonique sans inventer de session id.\n"
        "Si tu ne peux pas produire une mutation valide, retourne no_change.\n\n"
        "CONTRAT:\n"
        "- mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change\n"
        "- rationale et fitmas_message obligatoires et non vides\n"
        "- move_session/lighten_day/update_session/replace_session exigent target_session_id\n"
        "- swap_sessions exige target_session_id et second_session_id\n"
        "- create_session exige target_date, new_sport_type, new_title, new_duration_min\n"
        "- mapping utile: downgrade/unplanned_skip/replace sans session claire -> lighten_day seulement si target_session_id existe, sinon no_change\n\n"
        "GARDE-FOUS MESSAGE:\n"
        "- si mutation_type=no_change, ne promets jamais que le plan est ajuste, deplace, libere ou mis a jour\n"
        "- si mutation_type=no_change, ne dis pas que tu vas construire un plan ou creer une seance\n"
        "- si mutation_type=no_change, fitmas_message doit rester neutre: comprehension, clarification, ou besoin de lire le plan\n"
        "- tutoie toujours l'utilisateur: jamais vous/vos/votre\n"
        "- ne laisse jamais fitmas_message tronque ou fini sur une demande incomplete comme \"confirme que c'est bien\"\n"
        "- ne rajoute pas une question si la reponse peut etre une clarification courte\n\n"
        f"PAYLOAD_INVALIDE:\n{json.dumps(data, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n\n"
        "Retourne uniquement le JSON repare."
    )
    return _request_structured_json(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )


def _request_claude_decision_fallback(*, system: str, prompt: str) -> dict | None:
    """Use Claude as a schema fallback after a structured DeepSeek payload failed validation."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    result = gw.request_structured_json(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model="claude-haiku-4-5-20251001",
        fallback_model="claude-haiku-4-5-20251001",
        provider="claude",
    )
    logger.info(
        "structured_json.schema_fallback provider=%s model=%s ok=%s error=%s",
        result.provider,
        result.model,
        result.data is not None,
        result.error,
    )
    return result.data


def _classify_llm_exception(exc: BaseException) -> str:
    """Classify a raised exception so operators can triage failures.

    Returns a short stable label (`timeout`, `rate_limit`, `bad_request`,
    `auth`, `connection`, `api_other`, `json_parse`, `unknown`). The
    labels are log-only — `decide()` still returns None for every case.
    """
    return gw.classify_llm_exception(exc)


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
        tool_choice={"type": "auto"},
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

    tool_use_blocks = _tool_use_blocks(response)
    tool_use_block = tool_use_blocks[0] if tool_use_blocks else None
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

    tool_calls = [
        ToolCall(tool_name=str(getattr(block, "name", "")), arguments=dict(getattr(block, "input", {}) or {}))
        for block in tool_use_blocks
    ]
    tool_executions = execute_tool_calls(
        tool_calls,
        context=tool_context,
        max_tools=3,
        llm_round_trips=2,
        prompt_tokens_estimate=initial_prompt_tokens,
        response_tokens_estimate=initial_response_tokens,
    )
    followup_messages = list(initial_messages)
    followup_messages.append({"role": "assistant", "content": _serialize_content_blocks(getattr(response, "content", []))})
    tool_result_blocks = _tool_result_blocks(tool_use_blocks, tool_executions)
    followup_messages.append(
        {
            "role": "user",
            "content": tool_result_blocks,
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
            tool_name=_tool_execution_names(tool_executions),
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=True,
            tool_called=_any_tool_called(tool_executions),
            tool_latency_ms=_sum_tool_latency(tool_executions),
            tool_success=False,
            tool_error=_tool_errors(tool_executions) or "tool followup request failed",
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
    if data is None:
        data = _repair_decision_json_from_text(_message_text(final_response), model=model)
    _log_tool_session_trace(
        pipeline=tool_context.pipeline,
        tool_name=_tool_execution_names(tool_executions),
        tool_offered=True,
        context_policy=context_policy,
        tool_requested=True,
        tool_called=_any_tool_called(tool_executions),
        tool_latency_ms=_sum_tool_latency(tool_executions),
        tool_success=_all_executed_tools_ok(tool_executions) and data is not None,
        tool_error=_tool_errors(tool_executions) if data is not None else (_tool_errors(tool_executions) or "tool followup response was not valid JSON"),
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


def _tool_result_blocks(tool_use_blocks: list[Any], tool_executions: list[ToolExecution]) -> list[dict[str, Any]]:
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


def _tool_execution_names(tool_executions: list[ToolExecution]) -> str | None:
    names = [execution.result.tool_name for execution in tool_executions if execution.result.tool_name]
    return ",".join(names) if names else None


def _any_tool_called(tool_executions: list[ToolExecution]) -> bool:
    return any(execution.trace.tool_called for execution in tool_executions)


def _all_executed_tools_ok(tool_executions: list[ToolExecution]) -> bool:
    called = [execution for execution in tool_executions if execution.trace.tool_called]
    return bool(called) and all(execution.result.status == "ok" for execution in called)


def _sum_tool_latency(tool_executions: list[ToolExecution]) -> int | None:
    values = [execution.trace.tool_latency_ms for execution in tool_executions if execution.trace.tool_latency_ms is not None]
    return sum(values) if values else None


def _tool_errors(tool_executions: list[ToolExecution]) -> str | None:
    errors = [execution.result.error for execution in tool_executions if execution.result.error]
    return "; ".join(errors) if errors else None


def _repair_decision_json_from_text(raw_text: str | None, *, model: str = "claude-haiku-4-5-20251001") -> dict | None:
    """Convert a prose decision-like answer into canonical JSON once."""
    if not raw_text:
        return None
    if _looks_like_provider_tool_markup(raw_text):
        return None
    prompt = (
        "Convertis cette reponse coach en JSON FitMAS canonique.\n"
        "N'invente pas de champ, de session id, ni de mutation absente de la reponse brute.\n"
        "Si l'action n'est pas claire, retourne no_change.\n"
        "mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change.\n"
        "Champs requis: mutation_type, rationale, fitmas_message.\n"
        "Pour move_session/lighten_day/update_session/replace_session, target_session_id doit etre present si la reponse parle d'une seance existante.\n\n"
        "Pour create_session, target_date, new_sport_type, new_title et new_duration_min sont obligatoires.\n\n"
        "GARDE-FOUS:\n"
        "- si tu retournes no_change, ne promets pas que le plan est ajuste, modifie, deplace, libere ou mis a jour\n"
        "- si tu retournes no_change, ne dis pas que tu vas construire un plan ou creer une seance\n"
        "- si la reponse brute promet une action mais ne donne pas de mutation valide, reformule en clarification neutre\n"
        "- tutoie toujours l'utilisateur: jamais vous/vos/votre\n"
        "- fitmas_message doit etre complet, court, et ne doit pas finir sur une phrase coupee\n"
        "- ne rajoute pas de nouvelle question sauf si la reponse brute en contient deja une claire\n\n"
        "REPONSE_BRUTE:\n"
        f"{raw_text}\n\n"
        "Retourne uniquement le JSON."
    )
    return _request_structured_json(
        system="Tu repars strictement des mots fournis et tu retournes un JSON valide uniquement.",
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=1024,
    )


def _looks_like_provider_tool_markup(raw_text: str) -> bool:
    normalized = raw_text.strip().lower()
    return (
        "<｜dsml｜tool_calls>" in normalized
        or "<｜dsml｜invoke" in normalized
        or "invoke name=" in normalized
    )


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


def _tool_use_blocks(response: Any) -> list[Any]:
    return [
        block
        for block in (getattr(response, "content", []) or [])
        if getattr(block, "type", None) == "tool_use"
    ]
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
        sport_type = getattr(session, "sport_type", "running")
        session_type = getattr(session, "session_type", "")
        status = getattr(session, "completion_status", "planned")
        slot = _timeline_slot_kind(session)
        movable_target = slot == "free_flexible"
        status_key = str(status or "").strip().lower()
        can_swap_with_training = slot in {"training", "free_flexible"} and status_key not in {"done", "skipped", "canceled"}
        swappable = can_swap_with_training
        lines.append(
            f"- id={getattr(session, 'id', '?')} | date={date_value} | day={day} | "
            f"slot={slot} | movable_target={str(movable_target).lower()} | "
            f"swappable={str(swappable).lower()} | "
            f"can_swap_with_training={str(can_swap_with_training).lower()} | [{sport_type}/{session_type}] "
            f"{getattr(session, 'session_title', '')} | goal={getattr(session, 'session_goal', '')} | status={status}"
        )
    return "\n".join(lines)


def _timeline_slot_kind(session: object) -> str:
    sport = str(getattr(session, "sport_type", "") or "").strip().lower()
    session_type = str(getattr(session, "session_type", "") or "").strip().lower()
    flexibility = str(getattr(session, "flexibility", "") or "").strip().lower()
    status = str(getattr(session, "completion_status", "") or "").strip().lower()
    if status in {"done", "skipped", "canceled"}:
        return "protected_recovery" if sport in {"rest", "off"} or session_type in {"rest", "recovery", "mobility"} else "training"
    recovery_like = sport in {"rest", "off", ""} or session_type in {"rest", "recovery", "mobility"}
    if recovery_like and flexibility == "flexible":
        return "free_flexible"
    if recovery_like:
        return "protected_recovery"
    return "training"


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
