from __future__ import annotations

from fitmas.legacy.domain.coaching import coach_voice
from fitmas.legacy.decision.output_verifier import looks_like_action_claim

from .reply_types import FinalReplyContext


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
_MEMORY_CLAIM_FRAGMENTS = (
    "je retiens",
    "je note",
    "je garde en tete",
    "je garde ca en tete",
    "je garde ça en tete",
    "bien note",
    "bien noté",
)
_EXECUTION_REGISTRATION_FRAGMENTS = (
    "seance enregistree",
    "séance enregistrée",
    "nouvelle seance enregistree",
    "nouvelle séance enregistrée",
)


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
    if not context.memory_actions_applied and any(fragment in normalized for fragment in _MEMORY_CLAIM_FRAGMENTS):
        return False
    if not context.execution_actions_applied and any(fragment in normalized for fragment in _EXECUTION_REGISTRATION_FRAGMENTS):
        return False
    return True


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
