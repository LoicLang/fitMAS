from __future__ import annotations

import re

from fitmas.legacy.domain.coaching import coach_voice
from fitmas.legacy.decision.grounding import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.legacy.llm.gateway import request_text

from .reply_types import FinalReplyContext, RequestTextFn
from .reply_factual_verifier import _parse_post_event_verdict
from .reply_validation import is_valid_final_reply


def is_valid_close_turn_reply(reply: str | None, *, allow_outage_fallback: bool = False) -> bool:
    if not reply:
        return False
    text = str(reply).strip()
    if len(text) < 3 or len(text) > 140:
        return False
    if "?" in text:
        return False
    if _sentence_count(text) > 2:
        return False
    if not allow_outage_fallback and _looks_like_close_turn_outage_fallback(text):
        return False
    context = FinalReplyContext(
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="terminal_close",
    )
    return is_valid_final_reply(text, context)


def close_turn_outage_fallback_reply() -> str:
    return "Carre, on garde ca."


def _looks_like_close_turn_outage_fallback(text: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(text)
    canonical = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return canonical == "carre on garde ca"


def _sentence_count(text: str) -> int:
    endings = sum(1 for char in text if char in ".!?")
    return max(1, endings)


def build_close_turn_reply_verifier_prompt(
    *,
    user_text: str,
    previous_agent_text: str | None,
    outgoing_reply: str,
    grounding: ReplyGroundingPacket | None = None,
) -> tuple[str, str]:
    """Build a semantic verifier prompt for terminal social closes."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu es le verificateur terminal_close FitMAS.\n"
        "Le turn planner LLM a deja decide que le tour est une cloture sociale.\n"
        "Tu ne choisis pas d'action et tu ne modifies aucun planning.\n"
        "Tu verifies seulement si la phrase finale ferme naturellement le tour.\n"
        "Retourne uniquement un JSON strict: "
        '{"verdict":"allow|repair","reason":"court","repaired_reply":"texte si repair"}'
    )
    lines = [
        "Intent deja decide: terminal_close",
        f"Dernier message coach visible: {previous_agent_text or '(absent)'}",
        f"Dernier message coach visible (contexte social, pas source de verite planning): {previous_agent_text or '(absent)'}",
        f"Message user: {user_text or '(absent)'}",
    ]
    if grounding is not None:
        lines.extend(["Grounding autoritaire:", *render_grounding_packet_for_prompt(grounding)])
    lines.extend([
        "Reponse sortante a verifier:",
        outgoing_reply,
        "",
        "ALLOW seulement si la reponse:",
        "- ferme le tour en 1-2 phrases courtes;",
        "- ne pose aucune question et ne relance pas le user;",
        "- n'explique pas le routage social et ne cite pas le message user;",
        "- n'ajoute aucun jour, duree, zone, sport, seance ou action absent du grounding ou du dernier message user;",
        "- ne claim aucun changement planning, aucune confirmation et aucun commit;",
        "- n'utilise pas la phrase fallback technique 'Carre, on garde ca.'.",
        "REPAIR si une regle est violee.",
        "En repair, ecris une fermeture naturelle courte. Si les faits sont insuffisants, reste generique.",
    ])
    return system, "\n".join(lines)


def verify_close_turn_reply(
    reply: str | None,
    *,
    user_text: str,
    previous_agent_text: str | None,
    grounding: ReplyGroundingPacket | None = None,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Verify or repair a terminal close reply through a semantic LLM judge."""
    if not is_valid_close_turn_reply(reply, allow_outage_fallback=False):
        return None
    text = str(reply).strip()
    system, prompt = build_close_turn_reply_verifier_prompt(
        user_text=user_text,
        previous_agent_text=previous_agent_text,
        outgoing_reply=text,
        grounding=grounding,
    )
    raw = request_text_fn(system=system, prompt=prompt, max_tokens=350)
    verdict = _parse_post_event_verdict(raw)
    if verdict is None:
        return None
    if verdict.get("verdict") == "allow":
        return text
    if verdict.get("verdict") == "repair":
        repaired = str(verdict.get("repaired_reply") or "").strip()
        if is_valid_close_turn_reply(repaired, allow_outage_fallback=False):
            return repaired
    return None


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
            "REPAIR si une execution appliquee contient une date et que la reponse la transforme en aujourd'hui, demain ou hier.",
            "REPAIR si la reponse transforme un remplacement/liberation en deplacement, ou inverse un commit et un blocage.",
            "REPAIR si elle demande confirmation pour une action deja committee.",
            "En repair, garde 1-2 phrases courtes, sans nom technique, sans inventer de nouvelle action.",
        ]
    )
    return system, "\n".join(lines)


def build_uncommitted_reply_verifier_prompt(
    context: FinalReplyContext,
    outgoing_reply: str,
) -> tuple[str, str]:
    """Build a verifier prompt for replies where no plan mutation was committed."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu es le verificateur post-runtime FitMAS pour un tour sans commit planning.\n"
        "Tu ne lis pas le message utilisateur et tu ne deduis aucune intention.\n"
        "Tu compares uniquement l'etat machine du tour avec la reponse sortante.\n"
        "Retourne uniquement un JSON strict: "
        '{"verdict":"allow|repair","reason":"court","repaired_reply":"texte si repair"}'
    )
    lines = [
        f"Pipeline: {context.pipeline}",
        f"Capacite pipeline: {context.pipeline_capability}",
        "Events commits: aucun changement planning commit.",
    ]
    if context.pending_summary:
        lines.append(f"Confirmation en attente: {context.pending_summary}")
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
            "ALLOW seulement si la reponse respecte l'etat machine ci-dessus.",
            "ALLOW si elle mentionne une action memoire ou execution uniquement quand elle figure dans les actions appliquees.",
            "ALLOW si une confirmation est en attente et que le changement planning est presente comme une proposition ou une option a confirmer.",
            "REPAIR si elle parle d'un changement planning comme deja effectif, deja cale, deja remplace, deja deplace ou deja transforme.",
            "REPAIR si elle dit qu'une seance devient autre chose alors qu'il n'y a qu'une confirmation en attente.",
            "REPAIR si elle invente un commit, une date, une seance, un sport ou une duree absent des faits machine.",
            "REPAIR si une execution appliquee contient une date et que la reponse la transforme en aujourd'hui, demain ou hier.",
            "En repair, garde 1-2 phrases courtes, sans nom technique, sans inventer de nouvelle action.",
        ]
    )
    if context.pending_summary:
        lines.append("Pour une pending: termine par une demande de confirmation courte si utile.")
    return system, "\n".join(lines)


def verify_uncommitted_reply(
    reply: str | None,
    context: FinalReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Verify or repair a reply for a turn where no planning mutation was committed."""
    if context.committed_events:
        return verify_post_event_reply(reply, context, request_text_fn=request_text_fn)
    if not is_valid_final_reply(reply, context):
        return None
    text = str(reply).strip()
    system, prompt = build_uncommitted_reply_verifier_prompt(context, text)
    raw = request_text_fn(system=system, prompt=prompt, max_tokens=350)
    verdict = _parse_post_event_verdict(raw)
    if verdict is None:
        return None
    if verdict.get("verdict") == "allow":
        if _pending_reply_shape_is_valid(text, context):
            return text
        retry_raw = request_text_fn(
            system=system,
            prompt=(
                prompt
                + "\n\nVerdict precedent invalide: une confirmation est en attente, "
                "mais la reponse ne demande pas explicitement confirmation. "
                "Retourne REPAIR avec une phrase de proposition qui se termine par une confirmation courte."
            ),
            max_tokens=350,
        )
        retry_verdict = _parse_post_event_verdict(retry_raw)
        if retry_verdict is None or retry_verdict.get("verdict") != "repair":
            return None
        repaired = str(retry_verdict.get("repaired_reply") or "").strip()
        if is_valid_final_reply(repaired, context) and _pending_reply_shape_is_valid(repaired, context):
            return repaired
        return None
    if verdict.get("verdict") == "repair":
        repaired = str(verdict.get("repaired_reply") or "").strip()
        if is_valid_final_reply(repaired, context) and _pending_reply_shape_is_valid(repaired, context):
            return repaired
    return None


def _pending_reply_shape_is_valid(text: str, context: FinalReplyContext) -> bool:
    if not context.pending_summary:
        return True
    if context.committed_events:
        return True
    return "?" in str(text or "")


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
