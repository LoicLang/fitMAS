from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable


logger = logging.getLogger("fitmas.llm")

StructuredJsonFn = Callable[..., dict | None]
GatewayStructuredJsonFn = Callable[..., Any]
DowngradeFn = Callable[[dict | None], dict | None]


def repair_invalid_decision_payload(
    *,
    data: dict[str, Any] | None,
    system: str,
    prompt: str,
    request_structured_json_fn: StructuredJsonFn,
    downgrade_free_confirmation_fn: DowngradeFn,
) -> dict | None:
    if not data:
        return None
    repair_prompt = (
        "Le payload LLM suivant est invalide pour FitMAS.\n"
        "Repare-le en JSON FitMAS canonique sans inventer de session id, de seance ou de fait.\n"
        "Preserve les actions memoire/execution deja justes si elles sont compatibles avec le contexte.\n"
        "Si le message utilisateur indique seulement qu'une seance n'a pas ete faite, retourne response_type=\"no_change\" + execution_actions, pas requires_confirmation.\n"
        "Si tu ne peux pas produire une mutation planning valide, retourne no_change.\n\n"
        "CONTRAT:\n"
        "- format prefere: CoachDecision avec response_type=reply|no_change|mutation_decision|plan_patch|requires_confirmation\n"
        "- mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change\n"
        "- rationale et fitmas_message obligatoires et non vides\n"
        "- execution_actions autorise record_execution_update: target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence, evidence?\n"
        "- memory_actions autorise record_health_signal, record_availability, record_preference\n"
        "- pending_resolution autorise accept_pending, reject_pending, modify_pending, ignore, needs_clarification\n"
        "- pending_resolution.accept_pending peut porter selected_candidate_id pour choisir une option plan_patch_choice\n"
        "- pending_resolution.modify_pending exige requested_changes; reason est optionnel\n"
        "- requires_confirmation exige confirmation_reason et sert aux mutations planning risquees, pas aux updates execution simples\n"
        "- requires_confirmation avec plan_patch exige un objet PlanPatch canonique: {coach_message, confirmation_reason?, operations:[{operation_type,...,rationale}]}\n"
        "- si le payload invalide contient un wrapper de tool draft_*, copie uniquement payload.patch dans plan_patch\n"
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
    repaired = request_structured_json_fn(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    return downgrade_free_confirmation_fn(repaired)


def request_claude_decision_fallback(
    *,
    system: str,
    prompt: str,
    gateway_request_structured_json_fn: GatewayStructuredJsonFn,
    downgrade_free_confirmation_fn: DowngradeFn,
) -> dict | None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    result = gateway_request_structured_json_fn(
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
    return downgrade_free_confirmation_fn(result.data)


def repair_decision_json_from_text(
    raw_text: str | None,
    *,
    model: str = "claude-haiku-4-5-20251001",
    context_prompt: str | None = None,
    tool_result_summary: str | None = None,
    request_structured_json_fn: StructuredJsonFn,
    downgrade_free_confirmation_fn: DowngradeFn,
) -> dict | None:
    if not raw_text:
        return None
    if looks_like_provider_tool_markup(raw_text):
        return None
    context_block = f"\nCONTEXTE_ORIGINAL:\n{context_prompt}\n" if context_prompt else ""
    tools_block = f"\nRESULTATS_TOOLS:\n{tool_result_summary}\n" if tool_result_summary else ""
    repair_prompt = (
        "Convertis cette reponse coach en JSON FitMAS canonique.\n"
        "N'invente pas de champ, de session id, ni de mutation absente de la reponse brute.\n"
        "Format prefere: CoachDecision avec response_type, rationale, fitmas_message, memory_actions, execution_actions et pending_resolution si utile.\n"
        "Si l'action planning n'est pas claire, retourne response_type=\"no_change\".\n"
        "Si la reponse brute dit qu'une seance n'a pas ete faite, retourne no_change + execution_actions record_execution_update.\n"
        "Ne retourne jamais un simple mutation_type=no_change quand la reponse brute reconnait une execution faite/non faite: cela perdrait l'action execution.\n"
        "N'ajoute sport_type dans execution_actions que si le contexte le rend certain.\n"
        "execution_actions.record_execution_update: type, target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence?, evidence?.\n"
        "mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change.\n"
        "Compat legacy autorisee seulement si aucune action memoire/execution/pending n'est necessaire.\n"
        "Champs requis: response_type, rationale, fitmas_message.\n"
        "Pour move_session/lighten_day/update_session/replace_session, target_session_id doit etre present si la reponse parle d'une seance existante.\n\n"
        "Pour create_session, target_date, new_sport_type, new_title et new_duration_min sont obligatoires.\n\n"
        "GARDE-FOUS:\n"
        "- n'utilise jamais response_type=requires_confirmation sans plan_patch ou mutation_decision structure\n"
        "- si la reponse brute propose une option a confirmer mais ne contient pas de patch structure, retourne no_change avec une question courte\n"
        "- si tu retournes no_change, ne promets pas que le plan est ajuste, modifie, deplace, libere ou mis a jour\n"
        "- si tu retournes no_change, ne dis pas que tu vas construire un plan ou creer une seance\n"
        "- si la reponse brute promet une action mais ne donne pas de mutation valide, reformule en clarification neutre\n"
        "- tutoie toujours l'utilisateur: jamais vous/vos/votre\n"
        "- fitmas_message doit etre complet, court, et ne doit pas finir sur une phrase coupee\n"
        "- ne rajoute pas de nouvelle question sauf si la reponse brute en contient deja une claire\n\n"
        "EXEMPLE OBLIGATOIRE:\n"
        "REPONSE_BRUTE: \"Hier n'a pas tenu, compris. Le footing de ce matin est toujours en place.\"\n"
        "JSON: {\"response_type\":\"no_change\",\"rationale\":\"execution manquee comprise sans mutation planning\",\"fitmas_message\":\"Hier n'a pas tenu, compris. Le footing de ce matin reste en place.\",\"execution_actions\":[{\"type\":\"record_execution_update\",\"target_ref\":\"seance d'hier\",\"status\":\"not_completed\",\"completed\":false,\"confidence\":0.8,\"evidence\":\"Hier n'a pas tenu\"}]}\n\n"
        f"{context_block}"
        f"{tools_block}"
        "REPONSE_BRUTE:\n"
        f"{raw_text}\n\n"
        "Retourne uniquement le JSON."
    )
    data = request_structured_json_fn(
        system="Tu repars strictement des mots fournis et tu retournes un JSON valide uniquement.",
        messages=[{"role": "user", "content": repair_prompt}],
        model=model,
        max_tokens=1024,
    )
    return downgrade_free_confirmation_fn(data)


def repair_tool_result_summary(
    tool_executions: list[Any],
    *,
    payload_char_limit: int = 2500,
) -> str | None:
    lines = []
    for execution in tool_executions:
        result = execution.result
        payload_json = json.dumps(result.payload, ensure_ascii=False)
        if len(payload_json) > payload_char_limit:
            payload_json = payload_json[:payload_char_limit] + "...[truncated]"
        if result.summary or result.payload:
            lines.append(
                f"- {result.tool_name}: {result.summary or '(pas de resume)'}\n"
                f"  payload: {payload_json}"
            )
    return "\n".join(lines) or None


def looks_like_provider_tool_markup(raw_text: str) -> bool:
    normalized = raw_text.strip().lower()
    return (
        "<｜dsml｜tool_calls>" in normalized
        or "<｜dsml｜invoke" in normalized
        or "invoke name=" in normalized
    )
