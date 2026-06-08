from __future__ import annotations

from fitmas.legacy.decision.grounding import ReplyGroundingPacket
from fitmas.legacy.llm.gateway import request_text

from .reply_event_verifier import verify_close_turn_reply
from .reply_types import FinalReplyContext, RequestTextFn


def compose_close_turn_reply(
    *,
    user_text: str,
    previous_agent_text: str | None = None,
    grounding: ReplyGroundingPacket | None = None,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Compose a terminal social close reply from a tiny no-action context."""
    from .reply_backend import compose_final_reply

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
        extra_facts.append(
            "Premiere proposition rejetee par le verifier ou reservee aux outages. "
            "Recompose une fermeture courte, sans nouveau fait."
        )
    return FinalReplyContext(
        user_text=user_text,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="terminal_close",
        extra_facts=tuple(extra_facts),
    )
