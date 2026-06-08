from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from fitmas.legacy.domain.coaching import coach_voice

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


_ACTION_VERBS = (
    "libere",
    "deplace",
    "remplace",
    "supprime",
    "decale",
    "bascule",
    "echange",
    "retire",
    "annule",
    "ajoute",
    "cale",
    "glisse",
    "inverse",
    "mis",
    "pose",
    "permute",
    "swap",
    "swappe",
)
_NEGATION_RE = re.compile(r"\bn[e']\s*$", re.IGNORECASE)
_PRONOUN_PATTERNS = tuple(
    re.compile(
        rf"\b(?:je\s+|j['’]\s*)(?:te\s+|vous\s+|le\s+|la\s+|les\s+|me\s+|l['’]\s*)?(?:(?:ai|avais|viens\s+de)\s+)?{verb}\w*\b",
        re.IGNORECASE,
    )
    for verb in _ACTION_VERBS
)
_PROPOSAL_MARKERS = (
    "je propose",
    "je peux",
    "je pourrais",
    "veux-tu",
    "tu veux",
    "tu confirmes",
    "ok pour",
    "d'accord pour",
    "si tu veux",
    "si tu confirmes",
)
_CONFIRM_ACTION_RE = re.compile(
    r"\b(?:je\s+|j['’]\s*)confirme\s+(?:ce|cet|cette|l['’])\s+"
    r"(?:swap|echange|deplacement|changement|report|decalage|mutation)\b",
    re.IGNORECASE,
)
_REPAIR_SYSTEM = (
    "Tu es FitMAS. Une de tes reponses precedentes contenait un verbe "
    "d'action 1ere personne (\"je deplace\", \"je libere\", \"j'echange\"...) "
    "alors qu'aucune mutation planning n'a ete committee ce tour. Reecris "
    "ta reponse SANS claim une action.\n\n"
    "Voix coach (regles imperatives):\n"
    "- Le message est envoye TEL QUEL au user. Voix d'un coach humain, jamais voix de bot.\n"
    "- Pas d'etiquette technique (\"plan modifie\", \"mutation enregistree\", \"swap applique\").\n"
    "- Pas de phrase generique du genre \"je n'ai applique aucun changement sur ce tour\".\n"
    "- Court (1-2 phrases). Reconnais ce que le user vient de dire si pertinent.\n"
    "- Soit tu reformules sans verbe mutation 1ere personne (\"X serait mieux\", \"je peux X si tu veux\"), "
    "soit tu poses UNE question courte de clarification.\n"
    "- Tu reponds UNIQUEMENT avec le texte de la nouvelle reply. Pas de JSON, pas de markdown, pas d'explication."
)


def looks_like_action_claim(reply_text: str) -> bool:
    if not reply_text:
        return False
    normalized = _strip_accents(reply_text)
    lower = normalized.lower()
    if any(marker in lower for marker in _PROPOSAL_MARKERS):
        return False
    if _CONFIRM_ACTION_RE.search(normalized):
        return True
    for pattern in _PRONOUN_PATTERNS:
        for match in pattern.finditer(normalized):
            preceding = normalized[: match.start()]
            if _NEGATION_RE.search(preceding):
                continue
            return True
    return False


def build_claim_repair_prompt(*, original_reply: str, user_text: str) -> tuple[str, str]:
    user_prompt = (
        f"Message du user: {user_text or '(aucun)'}\n\n"
        f"Ta reponse a reecrire (elle claim une action sans qu'aucune mutation soit committee):\n"
        f"\"{original_reply.strip()}\"\n\n"
        "Reecris cette reponse en respectant les regles ci-dessus."
    )
    return _REPAIR_SYSTEM, user_prompt


def outage_fallback_reply() -> str:
    return "Vu — rien de bouge sur ce tour. Tu veux que je bouge quoi concretement ?"


def safe_rewrite_for_claim_without_mutation() -> str:  # pragma: no cover - compatibility alias
    return outage_fallback_reply()


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def _claims_action_without_event(text: str, outcome: DecisionOutcome) -> bool:
    if _has_applied_event(outcome):
        return False
    return looks_like_action_claim(text)


def _has_applied_event(outcome: DecisionOutcome) -> bool:
    return any(result.status == "applied" and bool(result.event_id) for result in outcome.applied_commands)


def _claims_done(text: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(text)
    return any(fragment in normalized for fragment in ("c est fait", "c'est fait", "c est cale", "c'est cale"))
