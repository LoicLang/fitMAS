from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fitmas import coach_voice
from fitmas.claim_guard import looks_like_action_claim

from .context import CoachContext
from .outcome import DecisionOutcome


@dataclass(frozen=True, slots=True)
class VerificationResult:
    allowed: bool
    text: str
    reason: str | None = None


class OutputVerifier(Protocol):
    def verify(
        self,
        reply: str,
        outcome: DecisionOutcome,
        context: CoachContext,
    ) -> VerificationResult:
        ...


class DecisionOutputVerifier:
    def verify(
        self,
        reply: str,
        outcome: DecisionOutcome,
        context: CoachContext | None,
    ) -> VerificationResult:
        text = str(reply or "").strip()
        if not text:
            return VerificationResult(allowed=False, text="", reason="empty_reply")
        if coach_voice.message_has_user_facing_internal_jargon(text):
            return VerificationResult(allowed=False, text=text, reason="internal_jargon")
        if coach_voice.message_violates_coach_voice(text) or coach_voice.message_looks_receipt_style(text):
            return VerificationResult(allowed=False, text=text, reason="voice")
        if _claims_action_without_event(text, outcome):
            return VerificationResult(allowed=False, text=text, reason="uncommitted_action_claim")
        if outcome.kind in {"plan_pending", "plan_choice_pending"} and _claims_done(text):
            return VerificationResult(allowed=False, text=text, reason="pending_claims_done")
        return VerificationResult(allowed=True, text=text, reason=None)


def _claims_action_without_event(text: str, outcome: DecisionOutcome) -> bool:
    if _has_applied_event(outcome):
        return False
    return looks_like_action_claim(text)


def _has_applied_event(outcome: DecisionOutcome) -> bool:
    return any(result.status == "applied" and bool(result.event_id) for result in outcome.applied_commands)


def _claims_done(text: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(text)
    return any(fragment in normalized for fragment in ("c est fait", "c'est fait", "c est cale", "c'est cale"))
