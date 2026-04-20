"""Anti-mensonge "dire = faire" — Chantier 1bis du COACH-AUTONOMY-REFACTOR.

The coach must never affirm an action ("Je libere ce creneau", "Je deplace
cette seance") when no plan_mutation_event has been emitted on the current
turn. This module exposes the detection of such claims and a safe rewrite
that demotes them to an explicit proposal.

Verb forms cover the main mutation lexicon. We deliberately match the
infinitive plus 1st person singular present, with elision (j'ajoute) and
common spellings with/without accents.
"""

from __future__ import annotations

import re
import unicodedata


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
    "swap",
    "swappe",
)


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


_NEGATION_RE = re.compile(r"\bn[e']\s*$", re.IGNORECASE)
_PRONOUN_PATTERNS = tuple(
    re.compile(
        rf"\b(?:je\s+|j['’]\s*)(?:te\s+|vous\s+|le\s+|la\s+|les\s+|me\s+)?{verb}\w*\b",
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


def looks_like_action_claim(reply_text: str) -> bool:
    """Return True if the reply asserts a mutation action in 1st person.

    False when the verb is preceded by a negation (n', ne) or when the
    sentence already frames the action as a proposal (je propose, veux-tu).
    """
    if not reply_text:
        return False
    normalized = _strip_accents(reply_text)
    lower = normalized.lower()
    if any(marker in lower for marker in _PROPOSAL_MARKERS):
        return False
    for pattern in _PRONOUN_PATTERNS:
        for match in pattern.finditer(normalized):
            preceding = normalized[: match.start()]
            if _NEGATION_RE.search(preceding):
                continue
            return True
    return False


def safe_rewrite_for_claim_without_mutation() -> str:
    """Reply text used when a claim_without_mutation is detected.

    Sober and explicit: we don't pretend to know what the user wanted.
    The fallback asks for clarification rather than guessing."""
    return (
        "Je n'ai applique aucun changement sur ce tour. "
        "Dis-moi explicitement ce que tu veux que je deplace, remplace ou liberes "
        "et je le fais (ou je te propose une option a confirmer)."
    )
