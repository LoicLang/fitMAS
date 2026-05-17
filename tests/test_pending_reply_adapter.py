from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision.reply_request import ReplyResult
from fitmas.legacy.pending_reply_adapter import compose_pending_reply, pending_reply_outcome


class SpyComposer:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def compose(self, outcome, context, *, user_text: str = "", grounding_facts: tuple[str, ...] = ()):
        self.calls.append(
            {
                "outcome": outcome,
                "context": context,
                "user_text": user_text,
                "grounding_facts": grounding_facts,
            }
        )
        return ReplyResult(text=self.text, verified=True, fallback_used=False, reason=None)


def _pending():
    return SimpleNamespace(
        id=42,
        mutation_type="plan_patch",
        reason="week_coherence_requires_confirmation",
        summary="deplacer la seance",
        source_text="deplace vendredi",
    )


def test_pending_rejected_outcome_forbids_plan_commit_claims() -> None:
    outcome = pending_reply_outcome(mode="rejected", pending_confirmation=_pending())

    assert outcome.kind == "answer"
    assert outcome.applied_commands == ()
    assert "plan_committed" in outcome.reply_contract.forbidden_claims
    assert "pending_id=42" in outcome.explanation.evidence


def test_pending_kept_outcome_is_plan_pending_with_next_step() -> None:
    outcome = pending_reply_outcome(mode="kept", pending_confirmation=_pending())

    assert outcome.kind == "plan_pending"
    assert outcome.explanation.next_step == "Dis-moi si tu veux l'appliquer ou la modifier."
    assert outcome.reply_contract.mode == "pending_kept"


def test_pending_choice_invalid_outcome_is_plan_choice_pending() -> None:
    outcome = pending_reply_outcome(mode="choice_invalid_selection", pending_confirmation=_pending())

    assert outcome.kind == "plan_choice_pending"
    assert outcome.explanation.next_step == "Rechoisis parmi les options proposees."
    assert outcome.reply_contract.mode == "pending_choice_invalid_selection"


def test_compose_pending_reply_uses_decision_reply_composer() -> None:
    composer = SpyComposer("Composer garde la proposition ouverte.")

    text = compose_pending_reply(
        mode="kept",
        pending_confirmation=_pending(),
        user_text="j'attends",
        decision_reply_composer=composer,
    )

    assert text == "Composer garde la proposition ouverte."
    assert composer.calls[0]["outcome"].kind == "plan_pending"
    assert composer.calls[0]["user_text"] == "j'attends"
