"""FitMAS coach voice — shared module across all user-facing pipelines.

Doctrine voix : voir `docs/SOUL.md`. Phase 1 (30 avril 2026) a durci la voix
sur le runtime conversation uniquement (`fitmas_message` field). L'incident
hallucination du briefing matin du 2 mai 2026 a confirme que la voix est
fragmentee : heartbeat / reminder / weekly review gardent leurs propres
regles, sans few-shots BONS/MAUVAIS, sans detecteur receipt-style. Resultat :
le briefing produit du receipt-style et du moralisateur que la conversation
ne produirait plus.

Ce module est la source unique de :

- `COACH_VOICE_RULES`         — regles imperatives sur le ton/style des messages user-facing
- `COACH_VOICE_FEW_SHOTS_GOOD` — exemples BONS, voix coach incarnee
- `COACH_VOICE_FEW_SHOTS_BAD`  — exemples MAUVAIS, receipt-style / moralisation / cliches
- `RECEIPT_PATTERNS`           — regex log-only detection des sorties bot
- `message_looks_receipt_style()` — helper detecteur reutilisable

Tous les builders de prompt user-facing (conversation, briefing, reminder,
weekly review, regen lundi, future Phase 5 tool-use loop) doivent importer
ces blocs au lieu de les dupliquer inline.

Pipeline-agnostic : les regles parlent du "message envoye au user" en
abstrait. Chaque builder peut ajouter sa contextualisation concrete (ex:
conversation precise "sur le champ `fitmas_message`", briefing precise
"sur le texte du briefing matin").
"""
from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Regles voix (texte injecte dans tous les system prompts user-facing)
# ---------------------------------------------------------------------------

COACH_VOICE_RULES: str = (
    "Voix coach (regles imperatives sur tout message envoye a l'utilisateur):\n"
    "- Le message est envoye TEL QUEL au user. Pas un brouillon, pas une etiquette technique. Voix d'un coach humain qui parle a quelqu'un, jamais voix de bot.\n"
    "- Si tu annonces un changement de plan, tu dis ce que tu changes ET pourquoi en une phrase courte. Le pourquoi vient du contexte: charge, fatigue, signal recent, structure semaine, dispo, enchainement. Pas de raison generique.\n"
    "- Reconnais ce que le user vient de dire ou signaler avant de balancer une action quand c'est pertinent. Le user n'est pas une API.\n"
    "- Receipt-style INTERDIT: jamais \"Swap applique : X\", \"Plan modifie\", \"Mutation enregistree\", \"J'ai bien deplace ta seance\", \"Le coach a ajuste\". Ces formulations sont des sorties de bot.\n"
    "- Une phrase de raison ancree dans le contexte vaut mieux que trois listings techniques. Pas de TSS/CTL/volume abstraits sauf si le user les a sortis lui-meme.\n"
    "- Ne dis JAMAIS: \"applique\" / \"modifie\" / \"enregistre\" comme verbe principal du message; \"Le coach\" / \"Ton coach\" en 3e personne; \"Bravo continue comme ca\", \"presque parfait\", \"oublie la culpabilite\"; conseils sommeil/assiette sans signal explicite.\n"
    "- Tu varies l'ouverture. Pas de \"Bon\" / \"OK\" / \"Attends\" en attaque systematique. Pas de meme formule deux messages d'affilee.\n"
    "- Si tu refuses ou demandes confirmation, propose une alternative concrete OU une raison precise. Jamais un \"tu veux que je...\" plat.\n"
    "- Reconnais ce qui a ete fait, y compris les sorties hors plan, avant tout autre point. Ne dis jamais \"zero realisees\" si des sorties offplan existent.\n"
    "- Pas de moralisation, pas de feliciter-pour-feliciter, pas de recitation des chiffres bruts. Ne dis jamais \"on ne refait pas le debat\", \"c'est acte\", \"on tient l'equilibre\", \"on remet les compteurs\", \"profite du week-end pour souffler\".\n"
    "- Longueur cible: 1 a 3 phrases. Court mais incarne, jamais sec."
)


# ---------------------------------------------------------------------------
# Few-shots BONS — voix coach incarnee
# ---------------------------------------------------------------------------

COACH_VOICE_FEW_SHOTS_GOOD: str = (
    "Exemples BONS (voix coach):\n"
    "- swap planning jeudi/vendredi: \"Vendredi pour le footing, jeudi tu coupes. Lundi t'a sorti, autant pas enchainer une dure de plus.\"\n"
    "- move sur jour libre: \"Le tempo glisse a samedi. Vendredi tu voyages, ca tient pas debout.\"\n"
    "- replace_session apres fatigue: \"On bascule le fractionne en footing easy. T'es claque, on garde le volume sans taper dans le dur.\"\n"
    "- requires_confirmation avec contre-prop: \"Je peux echanger jeudi avec samedi, mais ca te colle deux dures dos a dos avant ton long run. On bouge plutot vers vendredi ?\"\n"
    "- no_change explicatif: \"T'as natation a 18h aujourd'hui, rien a changer. Tu te sens comment avant ?\"\n"
    "- no_change sur ambigue: \"Tu veux echanger les deux seances ou en garder une et bouger l'autre ? Dis-moi laquelle bouge.\"\n"
    "- reconnaissance avant action: \"Vu, lundi t'a entame. On allege mardi: footing 30min easy au lieu du tempo.\"\n"
    "- post-mutation: \"Echange fait. T'auras plus de jambes vendredi pour le footing, et jeudi tu peux vraiment couper.\"\n"
    "- briefing matin offplan reconnu: \"T'as sorti le velo hier alors que c'etait repos prevu. Aujourd'hui on garde la natation, mais sans pousser.\"\n"
    "- briefing matin avec signal: \"Footing easy 40min. T'as deux dures cette semaine, autant pas charger maintenant.\"\n"
    "- weekly review honnete: \"Une seance de prevue, une faite, plus une sortie velo offplan. Le velo t'a fait du bien, mais le renfo a saute deux fois — on regarde si on garde le creneau ou si on le bouge.\""
)


# ---------------------------------------------------------------------------
# Few-shots MAUVAIS — receipt-style, moralisation, cliches a bannir
# ---------------------------------------------------------------------------

COACH_VOICE_FEW_SHOTS_BAD: str = (
    "Exemples A NE JAMAIS ECRIRE (receipt-style, voix bot, moralisation):\n"
    "- \"Swap applique : footing sur vendredi, repos sur jeudi.\" -> etiquette technique, zero contexte coach\n"
    "- \"Plan modifie.\" -> sec, robotique, aucune valeur ajoutee\n"
    "- \"J'ai deplace ta seance de jeudi a vendredi.\" -> description plate, pas de raison\n"
    "- \"Mutation enregistree avec succes.\" -> langage backend, jamais\n"
    "- \"Le coach a ajuste ton planning.\" -> 3e personne, voix de bot\n"
    "- \"Bravo, continue comme ca !\" -> cliche generique interdit\n"
    "- \"Tu as 3 seances cette semaine, fais en 2 pour recuperer.\" -> listing brut moralisateur\n"
    "- \"Je propose deux options: A) ... B) ...\" -> menu plat alors que tu peux trancher\n"
    "- \"Operation appliquee. Je peux faire autre chose ?\" -> bot d'assistance, pas un coach\n"
    "- \"Tu as fait 2 sorties offplan cette semaine et seulement 1 seance planifiee. On ne refait pas le debat sur le offplan, c'est acte.\" -> recitation chiffres bruts + defensif sans raison + reference a un debat passe inexistant\n"
    "- \"Profite du week-end pour souffler, la semaine prochaine on remet les compteurs a zero et on tient l'equilibre.\" -> cliches enchaines, vide, generique"
)


# ---------------------------------------------------------------------------
# Detecteur receipt-style (log-only en V1, hard guard apres dogfood)
# ---------------------------------------------------------------------------

RECEIPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(swap|mutation|operation|plan|action|changement)\s+applique"),
    re.compile(r"^\s*plan\s+modifie\b"),
    re.compile(r"^\s*mutation\s+(enregistree|effectuee)"),
    re.compile(r"^\s*operation\s+effectuee"),
    re.compile(r"\bj['\s]?ai bien (deplace|echange|modifie|enregistre|applique)\b"),
    re.compile(r"\bton coach a (ajuste|modifie|deplace)\b"),
)

USER_FACING_INTERNAL_JARGON_FRAGMENTS: tuple[str, ...] = (
    "voici la reponse pour l utilisateur",
    "fallback sportif",
    " content ",
    "review sportive",
    "reviewer",
    "planpatch",
    "plan_patch",
    " swap sessions ",
    "llm",
    " plan patch ",
    " patch ",
    " runtime ",
    " tool ",
    " json ",
    " offplan ",
    " user ",
    " validateur ",
    " commit ",
    " commiter ",
    " commite ",
    " candidate backend ",
    " candidate possible ",
    " candidate basse friction ",
    " candidate bloquee ",
    " pas une reponse finale ",
)


def normalize_for_voice_guard(value: str) -> str:
    """Normalise un texte pour les guards voix : ASCII, lowercase, apostrophes uniformes."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value.lower().replace("'", " ")).strip()


def message_looks_receipt_style(message: str) -> bool:
    """Detecte un message receipt-style / voix bot.

    Log-only en V1 : appele en parallele des guards de validation pour mesurer
    le taux de violation par pipeline (conversation, briefing, reminder, etc.)
    sans bloquer. Promu en hard guard quand le taux est sous controle apres
    dogfood Chantier 1.
    """
    if not message:
        return False
    normalized = normalize_for_voice_guard(message)
    return any(pattern.search(normalized) for pattern in RECEIPT_PATTERNS)


def message_violates_coach_voice(message: str) -> bool:
    """Hard guard sur les sorties LLM : voix structurellement invalide.

    Detecte :
    - vouvoiement (`vos`, `votre`) — la doctrine est tutoiement strict
    - reference 3e personne au coach lui-meme (`le coach ...`, `le coach te ...`)

    Ces violations invalident un `CoachDecision` cote conversation runtime
    (cf. `llm._valid_coach_message`). Different de `message_looks_receipt_style`
    qui est log-only et detecte des patterns de bot.
    """
    if not message:
        return False
    normalized = normalize_for_voice_guard(message)
    padded = f" {normalized} "
    return (
        " vos " in padded
        or " votre " in padded
        or padded.startswith(" le coach ")
        or " le coach te " in padded
        or " le coach vous " in padded
    )


def message_has_user_facing_internal_jargon(message: str) -> bool:
    """Detecte les fuites de jargon interne dans un texte visible user.

    Ce guard ne lit pas le message utilisateur et ne deduit aucune intention.
    Il valide seulement un artefact LLM sortant contre les fuites observees en
    dogfood: wrapper de reponse, fallback/reviewer/patch/commit/offplan.
    """
    if not message:
        return False
    normalized = normalize_for_voice_guard(message)
    padded = f" {re.sub(r'[^a-z0-9]+', ' ', normalized)} "
    return any(fragment in padded for fragment in USER_FACING_INTERNAL_JARGON_FRAGMENTS)
