"""Final reply composition for coach-facing outcomes.

This module is deliberately thin. The backend still owns validation, commits
and audit events; this layer only asks the LLM to turn those machine facts into
the user-facing sentence when a normal path would otherwise use a canned reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Callable

from fitmas import coach_voice
from fitmas.claim_guard import looks_like_action_claim
from fitmas.grounding_contract import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.llm_gateway import request_text
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


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
    force: bool = False,
) -> str | None:
    if not force and request_text_fn is request_text and os.getenv("FITMAS_ENABLE_FINAL_REPLY_COMPOSER") == "0":
        return None
    system, prompt = build_final_reply_prompt(context)
    reply = request_text_fn(system=system, prompt=prompt, max_tokens=300)
    if not is_valid_final_reply(reply, context):
        return None
    return str(reply).strip()


def compose_close_turn_reply(
    *,
    user_text: str,
    previous_agent_text: str | None = None,
    grounding: ReplyGroundingPacket | None = None,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose a terminal social close reply from a tiny no-action context."""
    context = _close_turn_context(
        user_text=user_text,
        previous_agent_text=previous_agent_text,
    )
    reply = compose_final_reply(context, request_text_fn=request_text_fn, force=True)
    verified_reply = verify_close_turn_reply(
        reply,
        user_text=user_text,
        previous_agent_text=previous_agent_text,
        grounding=grounding,
        request_text_fn=request_text_fn,
    )
    if verified_reply:
        return verified_reply

    retry_context = _close_turn_context(
        user_text=user_text,
        previous_agent_text=previous_agent_text,
        retry_after_fallback_like=True,
    )
    retry_reply = compose_final_reply(retry_context, request_text_fn=request_text_fn, force=True)
    return verify_close_turn_reply(
        retry_reply,
        user_text=user_text,
        previous_agent_text=previous_agent_text,
        grounding=grounding,
        request_text_fn=request_text_fn,
    )


def _close_turn_context(
    *,
    user_text: str,
    previous_agent_text: str | None = None,
    retry_after_fallback_like: bool = False,
) -> FinalReplyContext:
    extra_facts = [
        "Intent: terminal_close",
        "Aucun changement planning n'a ete commit.",
        "Ne relance pas le user.",
        "Le user ferme socialement le dernier message: termine le tour, ne fais pas un mini-coaching.",
        "Ne commente pas l'intention du user et ne cite pas son message.",
        "N'ajoute pas d'invitation de suivi du type 'tu me dis si besoin'.",
        "Le dernier message coach est un contexte social, pas une source de verite planning.",
        "Ne mentionne aucun jour, duree, zone, sport ou prochaine seance sans grounding explicite.",
        "La phrase fallback technique 'Carre, on garde ca.' est reservee aux outages; ne l'utilise pas en sortie composee.",
        "Exemple si le dernier coach posait une question ouverte et le user ferme: Carre, on s'arrete la.",
        "Exemple si le dernier coach proposait 36 min footing et le user valide: Parfait. Tu deroules ca tranquille.",
    ]
    if previous_agent_text:
        extra_facts.append(f"Dernier message coach: {previous_agent_text}")
    if retry_after_fallback_like:
        extra_facts.append("Premiere proposition rejetee par le verifier ou reservee aux outages. Recompose une fermeture courte, sans nouveau fait.")
    return FinalReplyContext(
        user_text=user_text,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="terminal_close",
        extra_facts=tuple(extra_facts),
    )


def compose_no_change_reply(
    *,
    user_text: str,
    original_llm_reply: str,
    memory_actions_applied: tuple[str, ...] = (),
    execution_actions_applied: tuple[str, ...] = (),
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose the final visible reply for a validated no-plan-change turn."""
    context = FinalReplyContext(
        user_text=user_text,
        original_llm_reply=original_llm_reply,
        memory_actions_applied=memory_actions_applied,
        execution_actions_applied=execution_actions_applied,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="no_change",
        extra_facts=(
            "Response type: no_change",
            "Aucun changement planning n'a ete commit.",
            "Tu peux reformuler le brouillon, mais pas changer ses faits ni ajouter d'action.",
        ),
    )
    return compose_final_reply(context, request_text_fn=request_text_fn)


def compose_plan_lookup_reply(
    *,
    user_text: str,
    original_llm_reply: str,
    memory_actions_applied: tuple[str, ...] = (),
    execution_actions_applied: tuple[str, ...] = (),
    grounding: ReplyGroundingPacket | None = None,
    request_text_fn: RequestTextFn = request_text,
    verifier_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose a factual read-only reply and semantically verify against truth."""
    extra_facts = (
        "Response type: plan_lookup",
        "Aucun changement planning n'a ete commit.",
        "Question factuelle: ne change aucun fait date, jour, duree, distance, zone, intensite ou statut.",
        "Ne pose pas de question au user: reponds au lookup et ferme le tour.",
        "Si tu ne peux pas reformuler sans alterer les faits, garde le contenu du brouillon.",
    )
    if grounding is not None:
        extra_facts = extra_facts + (
            "Grounding autoritaire disponible ci-dessous; les faits planning doivent venir de lui.",
            *render_grounding_packet_for_prompt(grounding),
        )
    context = FinalReplyContext(
        user_text=user_text,
        original_llm_reply=original_llm_reply,
        memory_actions_applied=memory_actions_applied,
        execution_actions_applied=execution_actions_applied,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="plan_lookup",
        extra_facts=extra_facts,
    )
    reply = compose_final_reply(context, request_text_fn=request_text_fn)
    if grounding is not None:
        verified = verify_factual_reply(
            reply,
            grounding=grounding,
            pipeline_capability="plan_lookup",
            request_text_fn=verifier_text_fn,
        )
        if verified:
            return verified
        verified_original = verify_factual_reply(
            original_llm_reply,
            grounding=grounding,
            pipeline_capability="plan_lookup",
            request_text_fn=verifier_text_fn,
        )
        if verified_original:
            return verified_original
        return None
    if is_valid_plan_lookup_reply(reply, original_llm_reply=original_llm_reply):
        return str(reply).strip()
    if is_valid_plan_lookup_reply(original_llm_reply, original_llm_reply=original_llm_reply):
        return str(original_llm_reply).strip()
    return None


def compose_plan_adaptation_reply(
    *,
    policy_decision: AdaptationPolicyDecision,
    user_text: str = "",
    committed_events: tuple[str, ...] = (),
    candidate_summaries: tuple[str, ...] = (),
    extra_facts: tuple[str, ...] = (),
    request_text_fn: RequestTextFn = request_text,
    verifier_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose the visible reply after the adaptation policy has decided."""
    context = build_plan_adaptation_reply_context(
        policy_decision=policy_decision,
        user_text=user_text,
        committed_events=committed_events,
        candidate_summaries=candidate_summaries,
        extra_facts=extra_facts,
    )
    reply = compose_final_reply(context, request_text_fn=request_text_fn, force=True)
    if context.committed_events:
        return verify_post_event_reply(reply, context, request_text_fn=verifier_text_fn)
    if is_valid_final_reply(reply, context):
        return str(reply).strip()
    return None


def build_plan_adaptation_reply_context(
    *,
    policy_decision: AdaptationPolicyDecision,
    user_text: str = "",
    committed_events: tuple[str, ...] = (),
    candidate_summaries: tuple[str, ...] = (),
    extra_facts: tuple[str, ...] = (),
) -> FinalReplyContext:
    action = policy_decision.action
    useful_facts = [
        f"Decision adaptation: {action}",
        f"Risque policy: {policy_decision.risk_level}",
        f"Raison policy: {policy_decision.user_facing_reason}",
    ]
    if policy_decision.selected_candidate_id:
        useful_facts.append(f"Candidate selectionnee: {policy_decision.selected_candidate_id}")
    if candidate_summaries:
        useful_facts.extend(f"Option candidate: {summary}" for summary in candidate_summaries)
    elif policy_decision.candidate_options:
        useful_facts.extend(
            f"Option candidate: {candidate_id}"
            for candidate_id in policy_decision.candidate_options
        )
    useful_facts.extend(extra_facts)

    pending_summary: str | None = None
    blocked_events: tuple[BlockedEvent, ...] = ()
    allowed_to_claim_mutation = False
    context_committed_events: tuple[str, ...] = ()

    if action == "commit":
        if committed_events:
            allowed_to_claim_mutation = True
            context_committed_events = committed_events
            useful_facts.append("Contrainte: action deja commit; explique le resultat reel.")
        else:
            useful_facts.append(
                "Contrainte: policy commit sans event machine fourni; ne claim aucune action appliquee."
            )
    elif action == "pending_confirmation":
        pending_summary = (
            policy_decision.requires_confirmation_reason or policy_decision.user_facing_reason
        )
        useful_facts.append(
            "Contrainte: presente cette option comme une proposition a confirmer, pas comme faite."
        )
    elif action == "pending_choice":
        pending_summary = (
            policy_decision.requires_confirmation_reason or policy_decision.user_facing_reason
        )
        useful_facts.append("Contrainte: presente ces options comme des propositions non appliquees.")
    elif action == "block":
        blocked_events = (
            BlockedEvent(
                command="plan_adaptation",
                reason=policy_decision.user_facing_reason or policy_decision.reason,
            ),
        )
        useful_facts.append("Contrainte: explique le blocage sans proposer une action deja faite.")

    return FinalReplyContext(
        user_text=user_text,
        committed_events=context_committed_events,
        blocked_events=blocked_events,
        pending_summary=pending_summary,
        allowed_to_claim_mutation=allowed_to_claim_mutation,
        pipeline="conversation",
        pipeline_capability=f"plan_adaptation_{action}",
        extra_facts=tuple(useful_facts),
    )


def is_valid_plan_lookup_reply(reply: str | None, *, original_llm_reply: str) -> bool:
    if not reply:
        return False
    if "?" in str(reply):
        return False
    context = FinalReplyContext(
        original_llm_reply=original_llm_reply,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="plan_lookup",
    )
    if not is_valid_final_reply(reply, context):
        return False
    return True


def build_factual_reply_verifier_prompt(
    *,
    outgoing_reply: str,
    grounding: ReplyGroundingPacket,
    pipeline_capability: str,
) -> tuple[str, str]:
    """Build a semantic verifier prompt from DB grounding and the reply only."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu es le verificateur factualite FitMAS.\n"
        "Tu ne lis pas le message utilisateur et tu ne deduis aucune intention.\n"
        "Tu compares uniquement le grounding backend autoritaire avec la reponse sortante.\n"
        "Retourne uniquement un JSON strict: "
        '{"verdict":"allow|repair","reason":"court","repaired_reply":"texte si repair"}'
    )
    lines = [
        f"Capacite pipeline: {pipeline_capability}",
        "Grounding autoritaire:",
        *render_grounding_packet_for_prompt(grounding),
        "",
        "Reponse sortante a verifier:",
        outgoing_reply,
        "",
        "ALLOW seulement si chaque jour, date, statut, sport, duree, zone, seance ou trou planning mentionne est supporte par le grounding.",
        "REPAIR si la reponse contredit le grounding, ajoute un jour/date absent, ou dit qu'un creneau est vide alors qu'une session existe.",
        "REPAIR si elle transforme une question de verification planning en relance au user au lieu de donner la verite disponible.",
        "En repair, garde 1-2 phrases courtes, sans nom technique, sans inventer de nouvelle action.",
    ]
    if pipeline_capability == "plan_lookup":
        lines.append("Pour plan_lookup: ne pose pas de question au user; donne la reponse factuelle et ferme.")
    return system, "\n".join(lines)


def verify_factual_reply(
    reply: str | None,
    *,
    grounding: ReplyGroundingPacket,
    pipeline_capability: str,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Verify or repair a reply against authoritative grounding facts."""
    if not reply:
        return None
    text = str(reply).strip()
    if pipeline_capability == "plan_lookup" and "?" in text:
        return None
    context = FinalReplyContext(
        allowed_to_claim_mutation=False,
        pipeline="conversation" if pipeline_capability == "plan_lookup" else pipeline_capability,
        pipeline_capability=pipeline_capability,
    )
    if not is_valid_final_reply(text, context):
        return None

    system, prompt = build_factual_reply_verifier_prompt(
        outgoing_reply=text,
        grounding=grounding,
        pipeline_capability=pipeline_capability,
    )
    raw = request_text_fn(system=system, prompt=prompt, max_tokens=450)
    verdict = _parse_post_event_verdict(raw)
    if verdict is None:
        return None
    if verdict.get("verdict") == "allow":
        return text
    repaired = str(verdict.get("repaired_reply") or "").strip()
    if pipeline_capability == "plan_lookup" and "?" in repaired:
        return None
    if repaired and is_valid_final_reply(repaired, context):
        return repaired
    return None


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
