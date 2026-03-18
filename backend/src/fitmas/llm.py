from __future__ import annotations

import json
import os

from pydantic import BaseModel

_SOUL = """\
Tu es FitMAS, une equipe IA de coaching running.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme une equipe exigeante et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.\
"""


class MutationDecision(BaseModel):
    mutation_type: str        # "move_session" | "lighten_day" | "no_change"
    from_day: str | None = None
    to_day: str | None = None
    rationale: str            # 1 phrase, pour les change notes
    fitmas_message: str       # message envoye a l'utilisateur


def _client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def decide(user_text: str, plan_summary: str) -> MutationDecision | None:
    """
    Call the LLM to extract intent and decide a plan mutation.
    Returns None if LLM is unavailable (API key missing or error) — caller falls back to rules.
    """
    client = _client()
    if not client:
        return None

    prompt = f"""Plan de la semaine (resume):
{plan_summary}

Message de l'utilisateur:
{user_text}

Analyse ce message et decide quelle action prendre sur le plan de la semaine.

Reponds avec un JSON valide contenant exactement ces champs:
- "mutation_type": une de ces valeurs: "move_session", "lighten_day", "no_change"
- "from_day": le jour source si move_session (monday/tuesday/wednesday/thursday/friday/saturday/sunday), null sinon
- "to_day": le jour destination si move_session, null sinon
- "rationale": explication courte de la decision (1 phrase, utilise dans les notes de changement)
- "fitmas_message": message FitMAS a envoyer — court, contextuel, ancre dans le signal reel

Reponds uniquement avec le JSON, sans markdown, sans texte autour."""

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
        data = json.loads(raw.strip())
        return MutationDecision(**data)
    except Exception:
        return None


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(f"- {d.label}: {d.session_title} (priorite: {d.priority}, flexibilite: {d.flexibility})")
    return "\n".join(lines)
