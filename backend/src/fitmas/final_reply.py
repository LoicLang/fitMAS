"""Final reply composition for coach-facing outcomes.

This module is deliberately thin. The backend still owns validation, commits
and audit events; this layer only asks the LLM to turn those machine facts into
the user-facing sentence when a normal path would otherwise use a canned reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Callable

from fitmas import coach_voice
from fitmas.claim_guard import looks_like_action_claim
from fitmas.llm_gateway import request_text


RequestTextFn = Callable[..., str | None]


@dataclass(frozen=True, slots=True)
class BlockedEvent:
    command: str
    reason: str | None = None
    suggested_fix: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class FinalReplyContext:
    user_text: str = ""
    original_llm_reply: str = ""
    committed_events: tuple[str, ...] = ()
    blocked_events: tuple[BlockedEvent, ...] = ()
    pending_summary: str | None = None
    memory_actions_applied: tuple[str, ...] = ()
    execution_actions_applied: tuple[str, ...] = ()
    allowed_to_claim_mutation: bool = False
    pipeline: str = "conversation"
    pipeline_capability: str = "can_confirm"
    extra_facts: tuple[str, ...] = field(default_factory=tuple)


_FORBIDDEN_VISIBLE_FRAGMENTS = (
    "je n ai applique aucun changement",
    "je n'ai applique aucun changement",
    "dis moi explicitement",
    "dis-moi explicitement",
    "mutation enregistree",
    "operation effectuee",
    "plan modifie",
    "block_reason",
)
_COMMITTED_CONFIRMATION_FRAGMENTS = (
    "tu confirmes",
    "confirme",
    "ca te va",
    "ça te va",
)
_UNCOMMITTED_ACTION_CLAIM_FRAGMENTS = (
    "echange fait",
    "swap fait",
    "deplacement fait",
    "remplacement fait",
    "changement fait",
    "c est deplace",
    "c'est deplace",
    "c est cale",
    "c'est cale",
    "c est ajoute",
    "c'est ajoute",
)


def build_final_reply_prompt(context: FinalReplyContext) -> tuple[str, str]:
    """Build the repair/composition prompt from machine facts only."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu composes la reponse finale visible au user a partir de faits backend.\n"
        "Le backend a deja valide, bloque, commit ou cree une confirmation.\n"
        "Tu ne dois jamais inventer un commit. Tu ne dois jamais exposer les noms techniques "
        "(reviewer, patch, runtime, fallback, commit, JSON, tool, offplan).\n"
        "Reponds uniquement avec le texte final, sans JSON ni markdown."
    )
    lines = [
        f"Pipeline: {context.pipeline}",
        f"Capacite pipeline: {context.pipeline_capability}",
        f"Message user: {context.user_text or '(non fourni)'}",
    ]
    if context.original_llm_reply:
        lines.append(f"Brouillon LLM initial: {context.original_llm_reply}")
    if context.committed_events:
        lines.append("Evenements commits:")
        lines.extend(f"- {event}" for event in context.committed_events)
        lines.append("Contrainte: l'action est deja commit; ne demande pas confirmation.")
    else:
        lines.append("Aucun changement planning n'a ete commit.")
    if context.blocked_events:
        lines.append("Evenements bloques:")
        for event in context.blocked_events:
            bits = [event.command]
            if event.reason:
                bits.append(f"reason={event.reason}")
            if event.suggested_fix:
                bits.append(f"suggested_fix={event.suggested_fix}")
            if event.warning:
                bits.append(f"warning={event.warning}")
            lines.append("- " + " | ".join(bits))
    if context.pending_summary:
        lines.append(f"Confirmation en attente: {context.pending_summary}")
    if context.execution_actions_applied:
        lines.append("Execution appliquee:")
        lines.extend(f"- {item}" for item in context.execution_actions_applied)
    if context.memory_actions_applied:
        lines.append("Memoire appliquee:")
        lines.extend(f"- {item}" for item in context.memory_actions_applied)
    if context.extra_facts:
        lines.append("Faits utiles:")
        lines.extend(f"- {item}" for item in context.extra_facts)
    if not context.allowed_to_claim_mutation:
        lines.append("Contrainte: ne claim pas une action appliquee, deplacee, posee, calee ou enregistree.")
    lines.append("Ecris 1-2 phrases. Si c'est bloque, donne la raison concrete et une alternative simple.")
    return system, "\n".join(lines)


def is_valid_final_reply(reply: str | None, context: FinalReplyContext) -> bool:
    if not reply:
        return False
    text = str(reply).strip()
    if len(text) < 5 or len(text) > 500:
        return False
    normalized = coach_voice.normalize_for_voice_guard(text)
    if any(fragment in normalized for fragment in _FORBIDDEN_VISIBLE_FRAGMENTS):
        return False
    if coach_voice.message_violates_coach_voice(text):
        return False
    if coach_voice.message_has_user_facing_internal_jargon(text):
        return False
    if coach_voice.message_looks_receipt_style(text):
        return False
    if context.committed_events and any(fragment in normalized for fragment in _COMMITTED_CONFIRMATION_FRAGMENTS):
        return False
    if not context.allowed_to_claim_mutation:
        if looks_like_action_claim(text):
            return False
        if any(fragment in normalized for fragment in _UNCOMMITTED_ACTION_CLAIM_FRAGMENTS):
            return False
    return True


def compose_final_reply(
    context: FinalReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    if request_text_fn is request_text and os.getenv("FITMAS_ENABLE_FINAL_REPLY_COMPOSER") == "0":
        return None
    system, prompt = build_final_reply_prompt(context)
    reply = request_text_fn(system=system, prompt=prompt, max_tokens=300)
    if not is_valid_final_reply(reply, context):
        return None
    return str(reply).strip()


def build_post_event_reply_verifier_prompt(
    context: FinalReplyContext,
    outgoing_reply: str,
) -> tuple[str, str]:
    """Build a verifier prompt from post-mutation machine facts and reply only."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu es le verificateur post-mutation FitMAS.\n"
        "Tu ne lis pas le message utilisateur et tu ne deduis aucune intention.\n"
        "Tu compares uniquement les events machine deja commits/bloques avec la reponse sortante.\n"
        "Retourne uniquement un JSON strict: "
        '{"verdict":"allow|repair","reason":"court","repaired_reply":"texte si repair"}'
    )
    lines = [
        f"Pipeline: {context.pipeline}",
        f"Capacite pipeline: {context.pipeline_capability}",
    ]
    if context.committed_events:
        lines.append("Events commits:")
        lines.extend(f"- {event}" for event in context.committed_events)
    else:
        lines.append("Events commits: aucun")
    if context.blocked_events:
        lines.append("Events bloques:")
        for event in context.blocked_events:
            bits = [event.command]
            if event.reason:
                bits.append(f"reason={event.reason}")
            if event.suggested_fix:
                bits.append(f"suggested_fix={event.suggested_fix}")
            if event.warning:
                bits.append(f"warning={event.warning}")
            lines.append("- " + " | ".join(bits))
    if context.execution_actions_applied:
        lines.append("Execution appliquee:")
        lines.extend(f"- {item}" for item in context.execution_actions_applied)
    if context.memory_actions_applied:
        lines.append("Memoire appliquee:")
        lines.extend(f"- {item}" for item in context.memory_actions_applied)
    if context.extra_facts:
        lines.append("Faits machine utiles:")
        lines.extend(f"- {item}" for item in context.extra_facts)
    lines.extend(
        [
            "Reponse sortante a verifier:",
            outgoing_reply,
            "",
            "ALLOW seulement si chaque action, date, session, sport et duree mentionnes par la reponse est supporte par les events.",
            "REPAIR si la reponse ajoute un deplacement, swap, creation, suppression, remplacement, date ou cible absent des events.",
            "REPAIR si la reponse transforme un remplacement/liberation en deplacement, ou inverse un commit et un blocage.",
            "REPAIR si elle demande confirmation pour une action deja committee.",
            "En repair, garde 1-2 phrases courtes, sans nom technique, sans inventer de nouvelle action.",
        ]
    )
    return system, "\n".join(lines)


def verify_post_event_reply(
    reply: str | None,
    context: FinalReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Verify or repair a post-event reply against committed machine facts."""
    if not is_valid_final_reply(reply, context):
        return None
    text = str(reply).strip()
    if not context.committed_events:
        return text

    system, prompt = build_post_event_reply_verifier_prompt(context, text)
    raw = request_text_fn(system=system, prompt=prompt, max_tokens=350)
    verdict = _parse_post_event_verdict(raw)
    if verdict is None:
        return None
    if verdict.get("verdict") == "allow":
        return text
    if verdict.get("verdict") == "repair":
        repaired = str(verdict.get("repaired_reply") or "").strip()
        if is_valid_final_reply(repaired, context):
            return repaired
    return None


def _parse_post_event_verdict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"allow", "repair"}:
        return None
    payload["verdict"] = verdict
    if verdict == "repair" and not str(payload.get("repaired_reply") or "").strip():
        return None
    return payload


def outage_fallback_reply(context: FinalReplyContext) -> str:
    """Minimal fallback when the final composer is unavailable.

    This is an outage/system path, not the normal coach voice path.
    """
    if context.blocked_events:
        reason = _blocked_event_fallback(context.blocked_events[0])
        if reason:
            return reason
        return "Je ne peux pas le bouger proprement sur ce tour. Donne-moi une autre cible et je reprends."
    if context.pending_summary:
        return "Je peux le faire, mais je veux ta confirmation avant de toucher la semaine. Tu confirmes ?"
    if context.committed_events:
        return "C'est pris en compte."
    return "Je ne peux pas te repondre proprement la tout de suite. Reessaie dans un instant."


def _blocked_event_fallback(event: BlockedEvent) -> str:
    reason = str(event.reason or "").strip()
    if reason == "protected_recovery_target":
        return (
            "Je garde ce creneau en recuperation protegee. "
            "Si tu veux garder la seance, le bon move est un swap."
        )
    if reason == "same_sport_proximity":
        return (
            "Je ne rapproche pas deux seances du meme sport a moins de 48h. "
            "Donne-moi un jour plus eloigne ou un autre sport."
        )
    if reason == "occupied_training_target":
        return (
            "Le jour cible a deja une vraie seance. "
            "Si tu veux les echanger, on part sur un swap."
        )
    if event.suggested_fix:
        return str(event.suggested_fix).strip()
    if event.warning:
        return str(event.warning).strip()
    return ""
