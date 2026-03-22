from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from fitmas.temporal_resolver import resolve_temporal_context

SPORT_KEYWORDS = {
    "running": ("couru", "courir", "course", "footing", "run", "running"),
    "swimming": ("nage", "nagee", "nagé", "nagé", "natation", "piscine"),
    "cycling": ("velo", "vélo", "bike", "cycling", "roule", "roulé", "ride"),
    "strength": ("renfo", "muscu", "musculation", "gainage", "strength"),
    "climbing": ("escalade", "grimpe", "bloc", "voie", "climbing"),
}


@dataclass(frozen=True, slots=True)
class ActivityClaim:
    sport_type: str | None
    duration_min: int | None
    resolved_date_iso: str | None
    temporal_reference: str
    confidence: float
    source_text: str


def extract_activity_claim(
    text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> ActivityClaim | None:
    lowered = text.lower()
    if not any(token in lowered for token in ("j'ai", "je fais", "je viens de", "fait", "couru", "nag", "roul", "grimp", "renfo", "muscu")):
        return None

    sport_type = _extract_sport(lowered)
    duration_min = _extract_duration_min(lowered)
    temporal = resolve_temporal_context(text, timezone_name=timezone_name, now=now)
    if sport_type is None and duration_min is None and temporal.primary_reference == "unspecified":
        return None

    confidence = 0.55
    if sport_type:
        confidence += 0.2
    if duration_min:
        confidence += 0.15
    if temporal.resolved_date:
        confidence += 0.1

    return ActivityClaim(
        sport_type=sport_type,
        duration_min=duration_min,
        resolved_date_iso=temporal.resolved_date.isoformat() if temporal.resolved_date else None,
        temporal_reference=temporal.primary_reference,
        confidence=min(confidence, 0.95),
        source_text=text.strip(),
    )


def merge_activity_claims(claims: Sequence[ActivityClaim]) -> ActivityClaim | None:
    valid = [claim for claim in claims if claim is not None]
    if not valid:
        return None
    latest = valid[-1]
    sport_type = latest.sport_type
    duration_min = latest.duration_min
    resolved_date_iso = latest.resolved_date_iso
    temporal_reference = latest.temporal_reference
    confidence = latest.confidence
    source_text = latest.source_text

    for claim in reversed(valid[:-1]):
        if sport_type is None and claim.sport_type is not None:
            sport_type = claim.sport_type
        if duration_min is None and claim.duration_min is not None:
            duration_min = claim.duration_min
        if resolved_date_iso is None and claim.resolved_date_iso is not None:
            resolved_date_iso = claim.resolved_date_iso
            temporal_reference = claim.temporal_reference
        confidence = max(confidence, claim.confidence)

    return ActivityClaim(
        sport_type=sport_type,
        duration_min=duration_min,
        resolved_date_iso=resolved_date_iso,
        temporal_reference=temporal_reference,
        confidence=confidence,
        source_text=source_text,
    )


def format_activity_claim_for_prompt(claim: ActivityClaim | None) -> str:
    if claim is None:
        return ""
    return (
        "Claim activite recent utilisateur:\n"
        f"- sport: {claim.sport_type or 'unknown'}\n"
        f"- duree_min: {claim.duration_min if claim.duration_min is not None else 'unknown'}\n"
        f"- date_resolue: {claim.resolved_date_iso or 'unknown'}\n"
        f"- reference_temps: {claim.temporal_reference}\n"
        f"- confiance: {claim.confidence:.2f}\n"
        f"- source: {claim.source_text}\n"
    )


def extract_recent_activity_claim(
    conversation_history: Sequence[dict],
    *,
    current_text: str,
    timezone_name: str | None,
    now: datetime | None = None,
) -> ActivityClaim | None:
    claims: list[ActivityClaim] = []
    for msg in conversation_history[-6:]:
        if msg.get("role") != "user":
            continue
        claim = extract_activity_claim(str(msg.get("text") or ""), timezone_name=timezone_name, now=now)
        if claim is not None:
            claims.append(claim)
    current_claim = extract_activity_claim(current_text, timezone_name=timezone_name, now=now)
    if current_claim is not None:
        claims.append(current_claim)
    return merge_activity_claims(claims)


def _extract_sport(lowered: str) -> str | None:
    for sport, keywords in SPORT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return sport
    return None


def _extract_duration_min(lowered: str) -> int | None:
    hour_min_match = re.search(r"(\d+)\s*h(?:\s*(\d{1,2}))?", lowered)
    if hour_min_match:
        hours = int(hour_min_match.group(1))
        minutes = int(hour_min_match.group(2) or 0)
        return hours * 60 + minutes
    minute_match = re.search(r"(\d+)\s*(?:min|mn|minutes?)", lowered)
    if minute_match:
        return int(minute_match.group(1))
    return None
