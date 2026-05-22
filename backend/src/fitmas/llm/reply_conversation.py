from __future__ import annotations

from fitmas.decision.grounding import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.llm.gateway import request_text

from .reply_factual_verifier import (
    _grounded_plan_lookup_fallback_reply,
    _plan_lookup_hard_guard_allows,
    verify_factual_reply,
)
from .reply_types import FinalReplyContext, RequestTextFn
from .reply_validation import is_valid_final_reply, is_valid_plan_lookup_reply
from .reply_verifiers import verify_uncommitted_reply


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
    from .reply_backend import compose_final_reply

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
    from .reply_backend import compose_final_reply

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
    from .reply_backend import compose_final_reply

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
