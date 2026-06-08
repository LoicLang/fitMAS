from __future__ import annotations

from typing import Any, Literal, Protocol

from fitmas.legacy.decision import DecisionExplanation, DecisionOutcome, DecisionReplyComposer, ReplyContract
from fitmas.legacy.decision.reply_request import ReplyResult


PendingReplyMode = Literal[
    "rejected",
    "kept",
    "modify_pending",
    "needs_clarification",
    "expired",
    "not_active",
    "choice_needs_selection",
    "choice_invalid_selection",
    "accept_error",
]


class _ReplyComposerLike(Protocol):
    def compose(
        self,
        outcome: DecisionOutcome,
        context: Any,
        *,
        user_text: str = "",
        grounding_facts: tuple[str, ...] = (),
    ) -> ReplyResult:
        ...


class _NoDraftReplyBackend:
    def compose(self, request) -> str | None:
        return None


def compose_pending_reply(
    *,
    mode: PendingReplyMode,
    pending_confirmation,
    pending_resolution: Any | None = None,
    user_text: str | None = None,
    decision_reply_composer: _ReplyComposerLike | None = None,
) -> str:
    outcome = pending_reply_outcome(
        mode=mode,
        pending_confirmation=pending_confirmation,
        pending_resolution=pending_resolution,
    )
    composer = decision_reply_composer or DecisionReplyComposer(reply_backend=_NoDraftReplyBackend())
    result = composer.compose(outcome, context=None, user_text=str(user_text or ""))
    return result.text or outcome.explanation.reason_summary


def pending_reply_outcome(
    *,
    mode: PendingReplyMode,
    pending_confirmation,
    pending_resolution: Any | None = None,
) -> DecisionOutcome:
    spec = _mode_spec(mode)
    return DecisionOutcome(
        kind=spec["kind"],
        commands=(),
        applied_commands=(),
        candidates=_candidate_summaries(pending_confirmation),
        selected_candidate_id=_selected_candidate_id(pending_resolution),
        explanation=DecisionExplanation(
            decision_label=spec["label"],
            reason_summary=spec["reason"],
            evidence=_evidence(pending_confirmation, pending_resolution),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step=spec["next_step"],
        ),
        reply_contract=ReplyContract(
            mode=f"pending_{mode}",
            audience="telegram",
            allowed_claims=spec["allowed_claims"],
            forbidden_claims=("plan_committed",),
        ),
    )


def _mode_spec(mode: PendingReplyMode) -> dict[str, Any]:
    return {
        "rejected": {
            "kind": "answer",
            "label": "Proposition refusee",
            "reason": "Je ne l'applique pas. Le planning reste inchange.",
            "next_step": None,
            "allowed_claims": ("pending_rejected",),
        },
        "kept": {
            "kind": "plan_pending",
            "label": "Proposition gardee",
            "reason": "La proposition reste en attente.",
            "next_step": "Dis-moi si tu veux l'appliquer ou la modifier.",
            "allowed_claims": ("pending_kept",),
        },
        "modify_pending": {
            "kind": "plan_pending",
            "label": "Modification demandee",
            "reason": "La proposition reste en attente.",
            "next_step": "Donne-moi le changement concret et je reprends.",
            "allowed_claims": ("pending_kept",),
        },
        "needs_clarification": {
            "kind": "plan_pending",
            "label": "Clarification requise",
            "reason": "La proposition reste en attente.",
            "next_step": "Dis-moi si tu veux l'appliquer ou la modifier.",
            "allowed_claims": ("pending_kept",),
        },
        "expired": {
            "kind": "plan_blocked",
            "label": "Confirmation expiree",
            "reason": "Cette confirmation n'est plus active. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
        "not_active": {
            "kind": "plan_blocked",
            "label": "Confirmation inactive",
            "reason": "Cette confirmation n'est plus active. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
        "choice_needs_selection": {
            "kind": "plan_choice_pending",
            "label": "Choix requis",
            "reason": "Une option doit etre choisie.",
            "next_step": "Choisis une des options proposees.",
            "allowed_claims": ("pending_kept",),
        },
        "choice_invalid_selection": {
            "kind": "plan_choice_pending",
            "label": "Choix introuvable",
            "reason": "Je ne retrouve pas cette option.",
            "next_step": "Rechoisis parmi les options proposees.",
            "allowed_claims": ("pending_kept",),
        },
        "accept_error": {
            "kind": "plan_blocked",
            "label": "Confirmation invalide",
            "reason": "La confirmation en attente n'est plus valide. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
    }[mode]


def _candidate_summaries(pending_confirmation) -> tuple[str, ...]:
    summary = str(getattr(pending_confirmation, "summary", "") or "").strip()
    return (summary,) if summary else ()


def _selected_candidate_id(pending_resolution: Any | None) -> str | None:
    selected = str(getattr(pending_resolution, "selected_candidate_id", "") or "").strip()
    return selected or None


def _evidence(pending_confirmation, pending_resolution: Any | None) -> tuple[str, ...]:
    evidence: list[str] = []
    pending_id = getattr(pending_confirmation, "id", None)
    if pending_id is not None:
        evidence.append(f"pending_id={pending_id}")
    mutation_type = str(getattr(pending_confirmation, "mutation_type", "") or "").strip()
    if mutation_type:
        evidence.append(f"mutation_type={mutation_type}")
    reason = str(getattr(pending_confirmation, "reason", "") or "").strip()
    if reason:
        evidence.append(f"reason={reason}")
    resolution_type = str(getattr(pending_resolution, "type", "") or "").strip()
    if resolution_type:
        evidence.append(f"resolution={resolution_type}")
    return tuple(evidence)
