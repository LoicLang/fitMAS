from __future__ import annotations

import json
from datetime import datetime

from fitmas import llm_gateway as gw
from fitmas.time_context import build_time_context, render_time_context
from fitmas.user_indications import (
    UserIndication,
    UserIndicationKind,
    UserIndicationScope,
    fallback_interpret_user_indication,
    indication_from_payload,
    should_attempt_indication_interpretation,
)

_INDICATION_SOUL = """\
Tu es le parseur d'indications utilisateur de FitMAS.
Tu n'inventes rien.
Tu classes seulement le message en signal exploitable par le systeme.
Tu reponds uniquement en JSON.\
"""


def _indication_richness(indication: UserIndication | None) -> int:
    if indication is None:
        return -1
    score = 0
    if indication.scope is not UserIndicationScope.UNKNOWN:
        score += 1
    if indication.time_reference is not None and indication.time_reference.resolved_date is not None:
        score += 2
    if indication.kind is UserIndicationKind.HEALTH_SIGNAL:
        if indication.body_zone:
            score += 1
        if indication.trigger_activity:
            score += 1
    if indication.kind is UserIndicationKind.EXECUTION_UPDATE:
        if indication.execution_sport_type:
            score += 1
        if indication.execution_duration_min:
            score += 1
    return score


def _prefer_richer_indication(indication: UserIndication | None, fallback: UserIndication | None) -> UserIndication | None:
    if indication is None:
        return fallback
    if fallback is None:
        return indication
    if indication.kind is not fallback.kind:
        return indication
    return fallback if _indication_richness(fallback) > _indication_richness(indication) else indication


def interpret_user_indication(
    user_text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> object | None:
    if not should_attempt_indication_interpretation(user_text):
        return None

    fallback = fallback_interpret_user_indication(user_text, timezone_name=timezone_name, now=now)
    if not gw.client():
        return fallback

    time_context = build_time_context(timezone_name, now=now)
    prompt = f"""{render_time_context(time_context)}
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
  "health": {{
    "body_zone": "shoulder" | "knee" | "achilles" | "back" | "hip" | "calf" | "ankle" | "general" | null,
    "trigger_activity": "swimming" | "running" | "cycling" | "strength" | "climbing" | "general" | null,
    "symptom_type": "pain" | "pain_tightness" | "soreness" | null,
    "severity": "low" | "moderate" | "high" | null
  }},
  "execution": {{
    "sport_type": "running" | "swimming" | "cycling" | "strength" | "climbing" | null,
    "duration_min": 0 | null
  }},
  "followup_needed": true | false,
  "followup_reason": "..." | null
}}

Regles:
- availability_constraint: indispo, contrainte logistique, voyage, fenetre non faisable
- health_signal: douleur, gene, symptome, fatigue locale ou generale
- execution_update: activite realisee ou corrigee
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
    return _prefer_richer_indication(indication, fallback)
