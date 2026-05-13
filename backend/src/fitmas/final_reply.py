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
import unicodedata
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


@dataclass(frozen=True, slots=True)
class HeartbeatReplyFact:
    category: str
    value: str


@dataclass(frozen=True, slots=True)
class HeartbeatReplyContext:
    role: str
    capability: str
    temporal: tuple[str, ...] = ()
    today_truth: tuple[str, ...] = ()
    yesterday_truth: tuple[str, ...] = ()
    week_digest: tuple[str, ...] = ()
    plan_window: tuple[str, ...] = ()
    active_facts: tuple[HeartbeatReplyFact, ...] = ()
    angle: str | None = None
    draft: str | None = None
    forbidden_claims: tuple[str, ...] = ()


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
_HEARTBEAT_INTERNAL_VISIBLE_FRAGMENTS = (
    " health ",
    " constraint ",
    " execution ",
    " patch ",
    " runtime ",
    " fallback ",
)
_HEARTBEAT_CONTEXT_MARKER_RE = re.compile(
    r"\[(health|constraint|execution|patch|runtime|fallback)\]\s*",
    flags=re.IGNORECASE,
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
        lines.append("Contrainte: la reponse doit presenter le changement comme une proposition et demander confirmation explicitement.")
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
    verifier_text_fn: RequestTextFn | None = None,
) -> str | None:
    """Compose the final visible reply for a validated no-plan-change turn."""
    verifier = verifier_text_fn or request_text_fn
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
    reply = compose_final_reply(context, request_text_fn=request_text_fn)
    verified = verify_uncommitted_reply(reply, context, request_text_fn=verifier)
    if verified:
        return verified
    return verify_uncommitted_reply(original_llm_reply, context, request_text_fn=verifier)


def compose_execution_report_reply(
    *,
    user_text: str,
    original_llm_reply: str,
    memory_actions_applied: tuple[str, ...] = (),
    execution_actions_applied: tuple[str, ...] = (),
    request_text_fn: RequestTextFn = request_text,
    verifier_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose the final reply for an execution report after applied actions are known."""
    context = FinalReplyContext(
        user_text=user_text,
        original_llm_reply=original_llm_reply,
        memory_actions_applied=memory_actions_applied,
        execution_actions_applied=execution_actions_applied,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="execution_report",
        extra_facts=(
            "Response type: execution_report",
            "Aucun changement planning n'a ete commit.",
            "Ne dis pas qu'une execution est notee, enregistree, ajoutee ou marquee sauf si `Execution appliquee` est listee.",
            "Si aucune execution n'est appliquee, reconnais le signal sans pretendre l'avoir enregistre.",
        ),
    )
    reply = compose_final_reply(context, request_text_fn=request_text_fn)
    return verify_uncommitted_reply(reply, context, request_text_fn=verifier_text_fn)


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
        fallback = _grounded_plan_lookup_fallback_reply(grounding)
        if (
            fallback
            and is_valid_final_reply(fallback, context)
            and _plan_lookup_hard_guard_allows(fallback, grounding)
        ):
            return fallback
        return None
    if is_valid_plan_lookup_reply(reply, original_llm_reply=original_llm_reply):
        return str(reply).strip()
    if is_valid_plan_lookup_reply(original_llm_reply, original_llm_reply=original_llm_reply):
        return str(original_llm_reply).strip()
    return None


def build_heartbeat_reply_prompt(context: HeartbeatReplyContext) -> tuple[str, str]:
    """Build a terminal heartbeat composer prompt from structured facts."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Ta responsabilite: compose le message heartbeat final visible au user.\n"
        "Le role heartbeat a prepare les faits; toi, tu transformes en texte naturel.\n"
        "Tu ne dois jamais recopier les categories internes ni les noms techniques.\n"
        "Tu ne dois jamais claim un changement planning sur un heartbeat read-only.\n"
        "Reponds uniquement avec le texte final, sans JSON ni markdown."
    )
    lines = [
        f"Role heartbeat: {context.role}",
        f"Capacite: {context.capability}",
    ]
    if context.temporal:
        lines.append("Temps:")
        lines.extend(f"- {item}" for item in context.temporal if str(item).strip())
    if context.today_truth:
        lines.append("Verite aujourd'hui:")
        lines.extend(f"- {item}" for item in context.today_truth if str(item).strip())
    if context.yesterday_truth:
        lines.append("Verite hier:")
        lines.extend(f"- {item}" for item in context.yesterday_truth if str(item).strip())
    if context.week_digest:
        lines.append("Digest semaine:")
        lines.extend(f"- {item}" for item in context.week_digest if str(item).strip())
    if context.plan_window:
        lines.append("Fenetre planning:")
        lines.extend(f"- {item}" for item in context.plan_window if str(item).strip())
    fact_values = _heartbeat_fact_values(context.active_facts)
    if fact_values:
        lines.append("Faits utiles:")
        lines.extend(f"- {item}" for item in fact_values)
    if context.angle:
        lines.append(f"Angle: {context.angle}")
    if context.draft:
        lines.append(f"Brouillon role heartbeat: {_heartbeat_prompt_value(context.draft)}")
    if context.forbidden_claims:
        lines.append("Claims interdits:")
        lines.extend(f"- {item}" for item in context.forbidden_claims if str(item).strip())
    lines.append("Ecris 1-3 phrases. Fond sportif concret, forme naturelle, pas de fiche interne.")
    return system, "\n".join(lines)


def compose_heartbeat_reply(
    context: HeartbeatReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    system, prompt = build_heartbeat_reply_prompt(context)
    reply = request_text_fn(system=system, prompt=prompt, max_tokens=320)
    if not is_valid_heartbeat_reply(reply):
        return None
    return str(reply).strip()


def is_valid_heartbeat_reply(reply: str | None) -> bool:
    if not reply:
        return False
    text = str(reply).strip()
    if len(text) < 5 or len(text) > 500:
        return False
    normalized = coach_voice.normalize_for_voice_guard(text)
    padded = f" {re.sub(r'[^a-z0-9]+', ' ', normalized)} "
    if any(fragment in padded for fragment in _HEARTBEAT_INTERNAL_VISIBLE_FRAGMENTS):
        return False
    context = FinalReplyContext(
        allowed_to_claim_mutation=False,
        pipeline="heartbeat",
        pipeline_capability="read_only",
    )
    return is_valid_final_reply(text, context)


def _heartbeat_fact_values(facts: tuple[HeartbeatReplyFact, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for fact in facts:
        value = str(fact.value or "").strip()
        if value:
            values.append(value)
    return tuple(values)


def _heartbeat_prompt_value(value: str) -> str:
    return _HEARTBEAT_CONTEXT_MARKER_RE.sub("", str(value or "")).strip()


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
    return verify_uncommitted_reply(reply, context, request_text_fn=verifier_text_fn)


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
    hard_guard_allows_text = True
    if pipeline_capability == "plan_lookup":
        hard_guard_allows_text = _plan_lookup_hard_guard_allows(text, grounding)

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
        return text if hard_guard_allows_text else None
    repaired = str(verdict.get("repaired_reply") or "").strip()
    if pipeline_capability == "plan_lookup" and "?" in repaired:
        return None
    if repaired and is_valid_final_reply(repaired, context):
        if pipeline_capability == "plan_lookup" and not _plan_lookup_hard_guard_allows(repaired, grounding):
            return None
        return repaired
    return None


def _plan_lookup_hard_guard_allows(reply: str | None, grounding: ReplyGroundingPacket) -> bool:
    if not reply:
        return False
    text = _normalize_factual_text(reply)
    if not text:
        return False
    allowed_durations = {
        int(fact.duration_min)
        for fact in grounding.plan_window
        if fact.duration_min is not None
    }
    for raw_value in re.findall(r"\b(\d{1,3})\s*(?:min|minute|minutes)\b", text):
        value = int(raw_value)
        if allowed_durations and value not in allowed_durations:
            return False

    allowed_dates = _grounding_allowed_dates(grounding)
    for raw_date in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text):
        if allowed_dates and raw_date not in allowed_dates:
            return False

    for fact in grounding.plan_window:
        if not _fact_is_referenced_in_reply(fact, text, grounding=grounding):
            continue
        if _reply_claims_empty_slot(text) and fact.slot_kind not in {"free_flexible", "closed"}:
            return False
        mentioned_sports = _mentioned_sports(text)
        non_negated_sports = {
            sport for sport, start in mentioned_sports if not _sport_mention_is_negated(text, start)
        }
        if non_negated_sports and fact.sport and fact.sport not in non_negated_sports:
            return False
        if _reply_claims_done(text) and fact.completion_status not in {"done", "completed"}:
            return False
        if _reply_claims_skipped(text) and fact.completion_status not in {"skipped", "cancelled", "canceled"}:
            return False
        if _reply_claims_adapted(text) and fact.completion_status != "adapted":
            return False
    return True


def _grounded_plan_lookup_fallback_reply(grounding: ReplyGroundingPacket) -> str | None:
    if not grounding.plan_window:
        return "Je ne vois aucune seance planifiee dans la fenetre lue."
    lines: list[str] = []
    for fact in grounding.plan_window[:6]:
        label = str(fact.day_label or fact.scheduled_date.isoformat()).strip().capitalize()
        title = str(fact.title or fact.sport or "Seance").strip()
        pieces = [f"{label}: {title}"]
        if fact.sport:
            pieces.append(fact.sport)
        if fact.duration_min is not None:
            pieces.append(f"{int(fact.duration_min)} min")
        if fact.completion_status:
            pieces.append(f"statut {fact.completion_status}")
        lines.append(", ".join(pieces) + ".")
    return " ".join(lines)


def _grounding_allowed_dates(grounding: ReplyGroundingPacket) -> set[str]:
    dates = {fact.scheduled_date.isoformat() for fact in grounding.plan_window}
    if grounding.local_date is not None:
        dates.add(grounding.local_date.isoformat())
    for refs in grounding.temporal_references.values():
        dates.update(ref.resolved_date.isoformat() for ref in refs)
    return dates


def _fact_is_referenced_in_reply(
    fact: Any,
    text: str,
    *,
    grounding: ReplyGroundingPacket,
) -> bool:
    if fact.scheduled_date.isoformat() in text:
        return True
    day_label = _normalize_factual_text(fact.day_label)
    if day_label and day_label in text:
        return True
    if grounding.local_date is not None:
        delta = (fact.scheduled_date - grounding.local_date).days
        if delta == 0 and "aujourd hui" in text:
            return True
        if delta == 1 and "demain" in text:
            return True
        if delta == -1 and "hier" in text:
            return True
    title = _normalize_factual_text(getattr(fact, "title", ""))
    return bool(title and title in text)


def _reply_claims_empty_slot(text: str) -> bool:
    return any(
        fragment in text
        for fragment in (
            "journee vide",
            "creneau vide",
            "aucune seance",
            "pas de seance",
            "pas d entrainement",
            "rien de prevu",
            "repos",
        )
    )


def _mentioned_sports(text: str) -> set[tuple[str, int]]:
    aliases = {
        "running": ("running", "run", "course", "footing", "fractionne"),
        "swimming": ("swimming", "natation", "nage", "nager", "piscine"),
        "cycling": ("cycling", "velo", "bike", "cyclisme"),
        "strength": ("strength", "renfo", "muscu", "musculation"),
        "climbing": ("climbing", "escalade"),
        "mobility": ("mobility", "mobilite"),
        "rest": ("rest", "repos"),
    }
    found: set[tuple[str, int]] = set()
    for sport, names in aliases.items():
        for name in names:
            pattern = rf"\b{re.escape(name)}\b"
            for match in re.finditer(pattern, text):
                found.add((sport, match.start()))
    return found


def _sport_mention_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start]
    return any(fragment in prefix for fragment in ("pas de", "pas d", "aucun", "aucune", "sans"))


def _reply_claims_done(text: str) -> bool:
    return _contains_any_word(text, ("faite", "fait", "realisee", "realise", "done"))


def _reply_claims_skipped(text: str) -> bool:
    return _contains_any_word(text, ("manquee", "manque", "skippee", "annulee", "annule"))


def _reply_claims_adapted(text: str) -> bool:
    return _contains_any_word(text, ("adaptee", "adapte", "adapted"))


def _contains_any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _normalize_factual_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9'-]+", " ", ascii_value).strip()


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
