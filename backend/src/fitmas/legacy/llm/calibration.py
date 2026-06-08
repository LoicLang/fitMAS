from __future__ import annotations

import json
from typing import Any

import fitmas.legacy.llm.gateway as gw
from fitmas.legacy.domain.coaching.calibration_needs import (
    CalibrationNeed,
    CalibrationNeedType,
    CalibrationResolution,
    fallback_ack_text,
)
from fitmas.legacy.core.time_context import build_time_context, render_time_context

_CALIBRATION_SOUL = """\
Tu es FitMAS, un coach multisport IA.
Tu ecris en francais.
Tu es humain, calme, precis.
Tu ne sonnes jamais comme un formulaire ni comme un bot.
Quand tu reformules un doute utile, tu le fais de maniere naturelle et breve.\
"""


def extract_calibration_resolution(
    *,
    user_text: str,
    need: CalibrationNeed,
    timezone_name: str | None,
    coach_context: dict[str, Any] | None = None,
) -> CalibrationResolution | None:
    if not gw.client():
        return None

    time_context = build_time_context(timezone_name)
    coach_block = _coach_block(coach_context or {})
    target_day = str(need.context.get("day") or "").strip() or "target_day"
    prompt = f"""{render_time_context(time_context)}
Besoin actif a resoudre:
- need_id: {need.id}
- type: {need.need_type.value}
- topic: {need.topic}
- why_now: {need.why_now}
- contexte: {json.dumps(need.context, ensure_ascii=False)}
- allowed_answers: {json.dumps(list(need.allowed_answers), ensure_ascii=False)}
{coach_block}

Message utilisateur:
{user_text}

Analyse si le message resout vraiment ce besoin actif.
N'invente rien hors du schema.
Si c'est ambigu, baisse la confiance ou demande un follow-up.

Retourne UNIQUEMENT un JSON:
{{
  "need_id": "{need.id}",
  "resolved": true|false,
  "normalized_value": {{}},
  "confidence": 0.0,
  "followup_needed": true|false,
  "followup_reason": "..." | null,
  "raw_summary": "resume court"
}}

Regles de normalisation:
- availability_window -> {{"day": "{target_day}", "windows": ["morning"|"evening"], "hard_blocked": ["morning"|"evening"]}}
- fatigue_state -> {{"session_id": 12, "state": "fresh"|"heavy"|"exhausted"}}
- constraint_scope -> {{"scope": "session_only"|"week"}}
"""
    data = gw.request_json(system=_CALIBRATION_SOUL, prompt=prompt, model="claude-haiku-4-5-20251001", max_tokens=400)
    resolution = _resolution_from_dict(data)
    if resolution is None or resolution.need_id != need.id:
        return None
    return _normalize_resolution_for_need(resolution, need)


def generate_calibration_ack(
    *,
    need: CalibrationNeed,
    resolution: CalibrationResolution,
    timezone_name: str | None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if not gw.client():
        return fallback_ack_text(need, resolution)
    time_context = build_time_context(timezone_name)
    coach_block = _coach_block(coach_context or {})
    prompt = f"""{render_time_context(time_context)}
{coach_block}
Tu viens de comprendre un point utile pour mieux tenir le plan.

Contexte:
- need_type: {need.need_type.value}
- why_now: {need.why_now}
- contexte cible: {json.dumps(need.context, ensure_ascii=False)}
- resolution: {json.dumps(resolution.normalized_value, ensure_ascii=False)}

Ecris une reponse courte, naturelle, en 1 ou 2 phrases max.
But:
- montrer ce que tu as compris
- dire a quoi ca sert
- ne jamais parler de "calibration", "schema", "systeme" ou "memoire"
- pas de liste
- pas de formule creuse
"""
    text = gw.request_text(system=_CALIBRATION_SOUL, prompt=prompt, model="claude-haiku-4-5-20251001", max_tokens=120)
    return text or fallback_ack_text(need, resolution)


def _coach_block(context: dict[str, Any]) -> str:
    if not context:
        return ""
    return (
        "Contexte coach:\n"
        f"- nom: {context.get('coach_name', 'FitMAS')}\n"
        f"- style: {context.get('coach_style', 'direct')}\n"
        f"- relation: {context.get('coach_relationship', '')}\n"
        f"- fait bien: {context.get('coach_do', '')}\n"
        f"- ne fait jamais: {context.get('coach_dont', '')}\n"
        f"- ame: {context.get('coach_soul', '')}\n"
    )


def _resolution_from_dict(data: dict[str, Any] | None) -> CalibrationResolution | None:
    if not isinstance(data, dict):
        return None
    try:
        return CalibrationResolution(
            need_id=str(data.get("need_id") or "").strip(),
            resolved=bool(data.get("resolved", False)),
            normalized_value=dict(data.get("normalized_value") or {}),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            followup_needed=bool(data.get("followup_needed", False)),
            followup_reason=str(data.get("followup_reason") or "").strip() or None,
            raw_summary=str(data.get("raw_summary") or "").strip(),
        )
    except (TypeError, ValueError):
        return None


def _normalize_resolution_for_need(
    resolution: CalibrationResolution,
    need: CalibrationNeed,
) -> CalibrationResolution:
    if need.need_type is not CalibrationNeedType.AVAILABILITY_WINDOW:
        return resolution
    target_day = str(need.context.get("day") or "").strip()
    if not target_day:
        return resolution
    normalized_value = dict(resolution.normalized_value)
    normalized_value["day"] = target_day
    return CalibrationResolution(
        need_id=resolution.need_id,
        resolved=resolution.resolved,
        normalized_value=normalized_value,
        confidence=resolution.confidence,
        followup_needed=resolution.followup_needed,
        followup_reason=resolution.followup_reason,
        raw_summary=resolution.raw_summary,
    )
