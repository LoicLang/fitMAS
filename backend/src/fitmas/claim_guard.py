"""Anti-mensonge "dire = faire" — garde post-LLM contre les claims d'action
sans mutation committee.

Le coach ne doit jamais affirmer une action ("Je libere ce creneau",
"Je deplace cette seance") quand aucun `plan_mutation_event` n'a ete emis
sur le tour courant.

Pipeline doctrine-correct (Chantier 1bis du plan 2 mai 2026) :

1. `looks_like_action_claim(reply)` detecte un claim 1ere personne
2. `build_claim_repair_prompt(reply, user_text)` construit un prompt repair
3. Pipeline appelle le LLM avec ce prompt -> reecrit en voix coach SANS claim
4. Si repair echoue (LLM down, output invalide) -> `outage_fallback_reply()`
   produit une ligne minimale honnete (cas outage explicite, pas template
   recurrent par design)

Avant Chantier 1bis : `safe_rewrite_for_claim_without_mutation()` retournait
une template canned doctrine-violante ("Je n'ai applique aucun changement
sur ce tour. Dis-moi explicitement ce que tu veux que je deplace..."). Cette
template a ete vue en prod dimanche soir 3 mai 2026, ironiquement apres
Chantier 1 voix unifiee ; la fix vient ici.
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
    "cale",
    "glisse",
    "inverse",
    "mis",
    "pose",
    "permute",
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
    if _CONFIRM_ACTION_RE.search(normalized):
        return True
    for pattern in _PRONOUN_PATTERNS:
        for match in pattern.finditer(normalized):
            preceding = normalized[: match.start()]
            if _NEGATION_RE.search(preceding):
                continue
            return True
    return False


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


def build_claim_repair_prompt(*, original_reply: str, user_text: str) -> tuple[str, str]:
    """Return `(system, user_prompt)` for the LLM repair call.

    The repair prompt asks the LLM to rewrite its claim-bearing reply into a
    coach-voice reply without claiming an uncommitted action. The pipeline
    is responsible for the actual LLM call (`llm_gateway.request_text`) and
    for handling outage via `outage_fallback_reply()`.
    """
    user_prompt = (
        f"Message du user: {user_text or '(aucun)'}\n\n"
        f"Ta reponse a reecrire (elle claim une action sans qu'aucune mutation soit committee):\n"
        f"\"{original_reply.strip()}\"\n\n"
        "Reecris cette reponse en respectant les regles ci-dessus."
    )
    return _REPAIR_SYSTEM, user_prompt


def outage_fallback_reply() -> str:
    """Outage fallback used when the repair LLM call fails or returns invalid text.

    Doctrine: "no helper produces a final conversational reply unless it is
    outage or a summary of a real committed event". This is the outage path:
    short, coach-voice, honest, not a recurring template by design.
    """
    return "Vu — rien de bouge sur ce tour. Tu veux que je bouge quoi concretement ?"


# Backward-compat alias kept for callers we have not migrated yet. New code
# should prefer the LLM repair flow via `build_claim_repair_prompt` +
# `outage_fallback_reply`.
def safe_rewrite_for_claim_without_mutation() -> str:  # pragma: no cover - shim
    return outage_fallback_reply()
