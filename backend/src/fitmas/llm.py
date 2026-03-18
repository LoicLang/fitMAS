from __future__ import annotations

import json
import logging
import os

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SOUL = """\
Tu es FitMAS, un coach running IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.\
"""


class MutationDecision(BaseModel):
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "no_change"
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    rationale: str            # 1 phrase, pour les change notes
    fitmas_message: str       # message envoye a l'utilisateur


_DAYS_FR_TO_EN = {
    "lundi": "monday", "mardi": "tuesday", "mercredi": "wednesday",
    "jeudi": "thursday", "vendredi": "friday", "samedi": "saturday",
    "dimanche": "sunday",
}


def _normalize_day(raw: str | None) -> str | None:
    """Convert French day names to English keys, pass through English names."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def _client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def decide(user_text: str, plan_summary: str, conversation_history: list[dict] | None = None) -> MutationDecision | None:
    """
    Call the LLM to extract intent and decide a plan mutation.
    Returns None if LLM is unavailable (API key missing or error) -- caller falls back to rules.
    """
    client = _client()
    if not client:
        logger.info("No Anthropic client available — falling back to rules")
        return None

    # Build conversation context
    history_block = ""
    if conversation_history:
        recent = conversation_history[-8:]  # last 8 messages for context
        lines = []
        for msg in recent:
            prefix = "Utilisateur" if msg["role"] == "user" else "FitMAS"
            lines.append(f"{prefix}: {msg['text']}")
        history_block = f"\nHistorique recent:\n" + "\n".join(lines) + "\n"

    prompt = f"""Plan de la semaine:
{plan_summary}
{history_block}
Nouveau message de l'utilisateur:
{user_text}

Analyse ce message et decide quelle action prendre sur le plan de la semaine.

Actions possibles:
- "move_session": deplacer une seance d'un jour a un autre (from_day + to_day)
- "swap_sessions": echanger les seances de deux jours (from_day + to_day)
- "lighten_day": alleger un jour (from_day seul)
- "update_session": modifier le titre ou l'objectif d'un jour (from_day + new_title et/ou new_goal)
- "no_change": aucune modification necessaire

Les jours doivent etre en anglais: monday, tuesday, wednesday, thursday, friday, saturday, sunday.

Exemples:
- "mardi c'est mort, je bascule sur jeudi" → move_session, from_day: "tuesday", to_day: "thursday"
- "mercredi j'ai une grosse journee" → lighten_day, from_day: "wednesday"
- "echange samedi et dimanche" → swap_sessions, from_day: "saturday", to_day: "sunday"
- "jeudi je prefere faire du fractionne" → update_session, from_day: "thursday", new_title: "Fractionne 8x400m"
- "ok ca me va" → no_change

Reponds avec un JSON valide contenant exactement ces champs:
- "mutation_type": une des valeurs ci-dessus
- "from_day": jour source (anglais) ou null
- "to_day": jour destination (anglais) ou null
- "new_title": nouveau titre de seance si update_session, null sinon
- "new_goal": nouvel objectif si update_session, null sinon
- "rationale": explication courte (1 phrase, pour les notes de changement)
- "fitmas_message": message a envoyer a l'utilisateur — court, direct, ancre dans le contexte

Reponds UNIQUEMENT avec le JSON, sans markdown, sans texte autour."""

    try:
        import anthropic
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SOUL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if the model wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        # Normalize French day names to English
        data["from_day"] = _normalize_day(data.get("from_day"))
        data["to_day"] = _normalize_day(data.get("to_day"))

        decision = MutationDecision(**data)
        logger.info(
            "LLM decision: %s (from=%s, to=%s) — %s",
            decision.mutation_type, decision.from_day, decision.to_day,
            decision.rationale,
        )
        return decision

    except Exception:
        logger.exception("LLM call failed — falling back to rules")
        return None


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(
            f"- {d.label} ({d.day}): {d.session_title} — {d.session_goal} "
            f"(priorite: {d.priority}, flexibilite: {d.flexibility})"
        )
    return "\n".join(lines)
