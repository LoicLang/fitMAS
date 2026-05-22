from __future__ import annotations

from fitmas.domain.planning.policy import AdaptationPolicyDecision

from .reply_types import BlockedEvent, FinalReplyContext, RequestTextFn
from .reply_verifiers import verify_post_event_reply, verify_uncommitted_reply
from .gateway import request_text


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
    from .reply_backend import compose_final_reply

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
