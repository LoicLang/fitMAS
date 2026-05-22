from __future__ import annotations

import os

from fitmas.decision.grounding import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.llm.gateway import request_text
from fitmas.llm.prompts.reply import ReplyPromptBlockedEvent, ReplyPromptInput, build_reply_prompt
from fitmas.domain.planning.policy import AdaptationPolicyDecision

from .reply_types import BlockedEvent, FinalReplyContext, RequestTextFn
from .reply_event_verifier import close_turn_outage_fallback_reply, outage_fallback_reply
from .reply_factual_verifier import (
    _grounded_plan_lookup_fallback_reply,
    _plan_lookup_hard_guard_allows,
    verify_factual_reply,
)
from .reply_validation import is_valid_final_reply, is_valid_plan_lookup_reply
from .reply_verifiers import (
    build_close_turn_reply_verifier_prompt,
    build_factual_reply_verifier_prompt,
    build_post_event_reply_verifier_prompt,
    build_uncommitted_reply_verifier_prompt,
    is_valid_close_turn_reply,
    verify_close_turn_reply,
    verify_post_event_reply,
    verify_uncommitted_reply,
)


def build_final_reply_prompt(context: FinalReplyContext) -> tuple[str, str]:
    """Build the repair/composition prompt from machine facts only."""
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline=context.pipeline,
            capability=context.pipeline_capability,
            user_text=context.user_text,
            original_llm_reply=context.original_llm_reply,
            committed_events=context.committed_events,
            blocked_events=tuple(
                ReplyPromptBlockedEvent(
                    command=event.command,
                    reason=event.reason,
                    suggested_fix=event.suggested_fix,
                    warning=event.warning,
                )
                for event in context.blocked_events
            ),
            pending_summary=context.pending_summary,
            memory_actions_applied=context.memory_actions_applied,
            execution_actions_applied=context.execution_actions_applied,
            allowed_to_claim_mutation=context.allowed_to_claim_mutation,
            extra_facts=context.extra_facts,
        )
    )
    return rendered.system, rendered.prompt


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
            "Ne dis pas que tu notes, retiens ou gardes en memoire sauf si `Memoire appliquee` est listee.",
            "Ne parle pas de seance enregistree sauf si `Execution appliquee` est listee.",
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
            "La source autoritaire pour la seance, le statut et la date est `Execution appliquee`, pas le brouillon initial.",
            "Ne dis pas qu'une execution est notee, enregistree, ajoutee ou marquee sauf si `Execution appliquee` est listee.",
            "Si `Execution appliquee` contient une date, conserve cette date ou reste neutre; ne la remplace pas par aujourd'hui, demain ou hier.",
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
