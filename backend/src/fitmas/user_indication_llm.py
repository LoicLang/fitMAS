from __future__ import annotations

import json
from datetime import datetime

from fitmas import llm_gateway as gw
from fitmas.time_context import build_time_context, render_time_context
from fitmas.user_indications import (
    UserIndication,
    indication_from_payload,
    should_attempt_indication_interpretation,
)

_INDICATION_SOUL = """\
Tu es le parseur d'indications utilisateur de FitMAS.
Tu n'inventes rien.
Tu classes seulement le message en signal exploitable par le systeme.
Tu reponds uniquement en JSON.\
"""

def interpret_user_indication(
    user_text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
    recent_agent_text: str | None = None,
    clarification_date: str | None = None,
    clarification_sport_type: str | None = None,
) -> object | None:
    if not should_attempt_indication_interpretation(user_text):
        return None

    if not gw.client():
        return None

    time_context = build_time_context(timezone_name, now=now)
    recent_agent_block = ""
    if recent_agent_text:
        recent_agent_block = f"\nDernier message coach:\n{recent_agent_text}\n"
    clarification_block = ""
    if clarification_date:
        clarification_block = (
            "\nContexte de clarification active:\n"
            f"- date cible: {clarification_date}\n"
            f"- sport cible: {clarification_sport_type or 'unknown'}\n"
            "- si le user repond juste 'oui' ou 'non', interprete-le comme la reponse a cette clarification.\n"
        )
    prompt = f"""{render_time_context(time_context)}
{recent_agent_block}{clarification_block}
Message utilisateur:
{user_text}

Classifie ce message comme un signal systeme.
Retourne UNIQUEMENT un JSON:
{{
  "kind": "availability_constraint" | "health_signal" | "execution_update" | "none",
  "confidence": 0.0,
  "scope": "single_window" | "single_day" | "week" | "unknown",
  "polarity": "unavailable" | "limited" | "signal" | null,
  "time_reference": {{
    "label": "demain soir" | null,
    "resolved_date": "YYYY-MM-DD" | null,
    "day_key": "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday" | null,
    "relative_reference": "today" | "tomorrow" | "yesterday" | "explicit_day" | "this_week" | null,
    "window": "morning" | "midday" | "evening" | null
  }},
  "availability": {{
    "trigger_activity": "swimming" | "running" | "cycling" | "strength" | "climbing" | "general" | null
  }},
  "health": {{
    "body_zone": "shoulder" | "knee" | "achilles" | "back" | "hip" | "calf" | "ankle" | "general" | null,
    "trigger_activity": "swimming" | "running" | "cycling" | "strength" | "climbing" | "general" | null,
    "symptom_type": "pain" | "pain_tightness" | "soreness" | null,
    "severity": "low" | "moderate" | "high" | null
  }},
  "execution": {{
    "sport_type": "running" | "swimming" | "cycling" | "strength" | "climbing" | null,
    "duration_min": 0 | null,
    "status": "done" | "not_done" | null
  }},
  "followup_needed": true | false,
  "followup_reason": "..." | null
}}

Regles:
- availability_constraint: indispo, contrainte logistique, voyage, fenetre non faisable
- health_signal: douleur, gene, symptome, fatigue locale ou generale
- execution_update: activite realisee ou non realisee, y compris reponse courte a une clarification en cours
- si ce n'est pas clairement un de ces cas, retourne "none"
- ne transforme pas une simple humeur vague en signal
- reste conservateur
"""
    data = gw.request_json(
        system=_INDICATION_SOUL,
        prompt=prompt,
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
    )
    indication = indication_from_payload(
        data,
        source_text=user_text,
        timezone_name=timezone_name,
        now=now,
    )
    return indication
