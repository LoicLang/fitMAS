from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

from fitmas.temporal_resolver import resolve_temporal_context
from fitmas.time_context import get_timezone

SPORT_KEYWORDS = {
    "running": ("couru", "courir", "course", "footing", "run", "running"),
    "swimming": ("nage", "nagee", "nagé", "nagé", "natation", "piscine"),
    "cycling": ("velo", "vélo", "bike", "cycling", "roule", "roulé", "ride"),
    "strength": ("renfo", "muscu", "musculation", "gainage", "strength"),
    "climbing": ("escalade", "grimpe", "bloc", "voie", "climbing"),
}

CLAIM_VERBS = ("j'ai", "je fais", "je viens de", "fait", "couru", "nag", "roul", "grimp", "renfo", "muscu")
CORRECTION_MARKERS = ("non", "plutot", "plutôt", "en fait", "finalement", "c'etait", "c'était")
NON_COMPLETION_MARKERS = (
    "je n'ai pas",
    "je nai pas",
    "j ai pas",
    "j'ai rien fait",
    "jai rien fait",
    "j ai rien fait",
    "rien fait",
    "pas couru",
    "pas nage",
    "pas nagé",
    "pas roule",
    "pas roulé",
    "pas fait",
)
COMPLETION_FACT_MARKERS = (
    "completed",
    "complete",
    "complété",
    "completee",
    "confirm",
    "fait",
    "realise",
    "réalisé",
    "couru",
    "nage",
    "nagé",
    "roule",
    "roulé",
)
NON_COMPLETION_FACT_MARKERS = (
    "skipped",
    "skip",
    "missed",
    "loup",
    "rate",
    "raté",
    "non_realise",
    "non realise",
    "not_completed",
    "not completed",
    "n_a_pas",
    "n'a pas",
    "pas_complete",
)
DAY_NAMES_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_NAMES_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


@dataclass(frozen=True, slots=True)
class ActivityClaim:
    sport_type: str | None
    duration_min: int | None
    resolved_date_iso: str | None
    temporal_reference: str
    confidence: float
    source_text: str


@dataclass(frozen=True, slots=True)
class NonCompletionClaim:
    sport_type: str | None
    resolved_date_iso: str | None
    confidence: float
    source_text: str


def extract_activity_claim(
    text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> ActivityClaim | None:
    lowered = text.lower()
    if any(marker in lowered for marker in NON_COMPLETION_MARKERS):
        return None
    temporal = resolve_temporal_context(text, timezone_name=timezone_name, now=now)
    has_claim_verb = any(token in lowered for token in CLAIM_VERBS)
    has_correction_marker = any(token in lowered for token in CORRECTION_MARKERS)
    if not has_claim_verb and not (has_correction_marker and temporal.primary_reference != "unspecified"):
        return None

    sport_type = _extract_sport(lowered)
    duration_min = _extract_duration_min(lowered)
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


def extract_non_completion_claim(
    text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
    default_date: date | None = None,
    default_sport_type: str | None = None,
    allow_contextual_short_answer: bool = False,
) -> NonCompletionClaim | None:
    lowered = text.lower()
    cleaned = " ".join(lowered.replace("?", " ").replace("!", " ").replace(".", " ").split())
    temporal = resolve_temporal_context(text, timezone_name=timezone_name, now=now)
    resolved_date = temporal.resolved_date or default_date
    if resolved_date is None:
        return None
    if not any(marker in lowered for marker in NON_COMPLETION_MARKERS):
        if not (allow_contextual_short_answer and cleaned in {"non", "nope", "nan"}):
            return None

    sport_type = _extract_sport(lowered) or default_sport_type
    if sport_type is None and "seance" not in lowered and "séance" not in lowered and default_sport_type is None:
        return None

    confidence = 0.78
    if sport_type is not None:
        confidence += 0.1
    if temporal.primary_reference != "unspecified" or default_date is not None:
        confidence += 0.07

    return NonCompletionClaim(
        sport_type=sport_type,
        resolved_date_iso=resolved_date.isoformat(),
        confidence=min(confidence, 0.95),
        source_text=text.strip(),
    )


def format_non_completion_claim_for_prompt(claim: NonCompletionClaim | None) -> str:
    if claim is None:
        return ""
    return (
        "Contestation execution utilisateur:\n"
        "- statut: non realise selon utilisateur\n"
        f"- sport: {claim.sport_type or 'unknown'}\n"
        f"- date_resolue: {claim.resolved_date_iso or 'unknown'}\n"
        f"- confiance: {claim.confidence:.2f}\n"
        f"- source: {claim.source_text}\n"
    )


def build_claim_fact_payloads(
    claim: ActivityClaim | None,
    *,
    activities: Sequence[Any],
    timezone_name: str | None,
) -> list[dict[str, Any]]:
    if claim is None:
        return []
    if claim.resolved_date_iso is None:
        return []
    if _claim_is_backed_by_activity(claim, activities=activities, timezone_name=timezone_name):
        return []
    return [
        {
            "category": "execution",
            "key": _claim_key(claim),
            "value": _claim_value(claim),
            "confidence": claim.confidence,
            "confirmed": True,
            "source": "conversation",
            "affects": ["conversation", "heartbeat"],
            "action": "upsert",
        }
    ]


def build_non_completion_fact_payloads(claim: NonCompletionClaim | None) -> list[dict[str, Any]]:
    if claim is None or claim.resolved_date_iso is None:
        return []
    sport = claim.sport_type or "unknown"
    return [
        {
            "category": "execution",
            "key": f"claimed_non_completion_{claim.resolved_date_iso}_{sport}",
            "value": (
                "Seance declaree non realisee par l'utilisateur: "
                f"{sport}, date {claim.resolved_date_iso}."
            ),
            "confidence": claim.confidence,
            "confirmed": True,
            "source": "conversation",
            "affects": ["conversation", "heartbeat"],
            "action": "upsert",
        }
    ]


def build_claim_correction_payloads(
    previous_claim: ActivityClaim | None,
    updated_claim: ActivityClaim | None,
) -> list[dict[str, Any]]:
    if previous_claim is None or updated_claim is None:
        return []
    previous_key = _claim_key(previous_claim) if previous_claim.resolved_date_iso else None
    updated_key = _claim_key(updated_claim) if updated_claim.resolved_date_iso else None
    if not previous_key or not updated_key or previous_key == updated_key:
        return []
    return [
        {
            "category": "execution",
            "key": previous_key,
            "value": previous_claim.source_text,
            "source": "conversation",
            "action": "archive",
        }
    ]


def build_execution_conflict_archive_payloads(
    active_facts: Sequence[Any],
    *,
    activity_claim: ActivityClaim | None = None,
    non_completion_claim: NonCompletionClaim | None = None,
) -> list[dict[str, Any]]:
    target_date_iso: str | None = None
    sport_type: str | None = None
    target_polarity: str | None = None

    if non_completion_claim is not None and non_completion_claim.resolved_date_iso is not None:
        target_date_iso = non_completion_claim.resolved_date_iso
        sport_type = non_completion_claim.sport_type
        target_polarity = "non_completion"
    elif activity_claim is not None and activity_claim.resolved_date_iso is not None:
        target_date_iso = activity_claim.resolved_date_iso
        sport_type = activity_claim.sport_type
        target_polarity = "completion"

    if target_date_iso is None or target_polarity is None:
        return []

    payloads: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for fact in active_facts:
        if _activity_value(fact, "category") != "execution":
            continue
        if _activity_value(fact, "active") is False:
            continue
        key = str(_activity_value(fact, "key") or "").strip()
        if not key or key in seen_keys:
            continue
        if not _execution_fact_matches_target(
            fact,
            target_date_iso=target_date_iso,
            sport_type=sport_type,
        ):
            continue
        fact_polarity = _execution_fact_polarity(fact)
        if fact_polarity is None or fact_polarity == target_polarity:
            continue
        seen_keys.add(key)
        payloads.append(
            {
                "category": "execution",
                "key": key,
                "value": str(_activity_value(fact, "value") or ""),
                "source": str(_activity_value(fact, "source") or "conversation"),
                "action": "archive",
            }
        )
    return payloads


def extract_claims_from_facts(
    facts: Sequence[Any],
    *,
    target_date: date | None = None,
) -> list[ActivityClaim]:
    extracted: list[ActivityClaim] = []
    for fact in facts:
        claim = _claim_from_fact(fact)
        if claim is None:
            continue
        if target_date is not None and claim.resolved_date_iso != target_date.isoformat():
            continue
        extracted.append(claim)
    return extracted


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


def is_activity_claim_correction(text: str, *, timezone_name: str | None) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in CORRECTION_MARKERS) and resolve_temporal_context(
        text,
        timezone_name=timezone_name,
    ).primary_reference != "unspecified"


def _claim_is_backed_by_activity(
    claim: ActivityClaim,
    *,
    activities: Sequence[Any],
    timezone_name: str | None,
) -> bool:
    for activity in activities:
        if _activity_local_date(activity, timezone_name=timezone_name) != claim.resolved_date_iso:
            continue
        activity_sport = _activity_value(activity, "sport_type")
        activity_duration = _activity_value(activity, "duration_min")
        if claim.sport_type and activity_sport == claim.sport_type:
            return True
        if claim.sport_type is None and claim.duration_min is not None and activity_duration == claim.duration_min:
            return True
    return False


def _execution_fact_matches_target(
    fact: Any,
    *,
    target_date_iso: str,
    sport_type: str | None,
) -> bool:
    key = str(_activity_value(fact, "key") or "").strip()
    if key.startswith("claimed_activity_"):
        claim = _claim_from_fact(fact)
        if claim is None or claim.resolved_date_iso != target_date_iso:
            return False
        if sport_type is None:
            return True
        return claim.sport_type == sport_type
    if key.startswith("claimed_non_completion_"):
        date_iso, fact_sport = _non_completion_from_key(key)
        if date_iso != target_date_iso:
            return False
        if sport_type is None:
            return True
        return fact_sport == sport_type

    haystack = f"{key} {str(_activity_value(fact, 'value') or '')}".lower()
    if sport_type is not None and not _haystack_mentions_sport(haystack, sport_type):
        return False
    if target_date_iso in haystack:
        return True
    target_date = date.fromisoformat(target_date_iso)
    return any(token in haystack for token in _day_tokens(target_date))


def _execution_fact_polarity(fact: Any) -> str | None:
    key = str(_activity_value(fact, "key") or "").strip()
    if key.startswith("claimed_activity_"):
        return "completion"
    if key.startswith("claimed_non_completion_"):
        return "non_completion"

    haystack = f"{key} {str(_activity_value(fact, 'value') or '')}".lower()
    if any(marker in haystack for marker in NON_COMPLETION_FACT_MARKERS):
        return "non_completion"
    if any(marker in haystack for marker in COMPLETION_FACT_MARKERS):
        return "completion"
    return None


def _haystack_mentions_sport(haystack: str, sport_type: str) -> bool:
    if sport_type in haystack:
        return True
    keywords = SPORT_KEYWORDS.get(sport_type, ())
    return any(keyword in haystack for keyword in keywords)


def _day_tokens(target_date: date) -> tuple[str, ...]:
    weekday = target_date.weekday()
    return (
        target_date.isoformat(),
        DAY_NAMES_EN[weekday],
        DAY_NAMES_FR[weekday],
    )


def _claim_key(claim: ActivityClaim) -> str:
    sport = claim.sport_type or "unknown"
    return f"claimed_activity_{claim.resolved_date_iso}_{sport}"


def _claim_value(claim: ActivityClaim) -> str:
    sport = claim.sport_type or "sport inconnu"
    duration = f"{claim.duration_min} min" if claim.duration_min is not None else "duree inconnue"
    return f"Activite declaree par l'utilisateur: {sport}, {duration}, date {claim.resolved_date_iso}, non loggee."


def _claim_from_fact(fact: Any) -> ActivityClaim | None:
    if _activity_value(fact, "category") != "execution":
        return None
    key = str(_activity_value(fact, "key") or "")
    match = re.match(r"claimed_activity_(\d{4}-\d{2}-\d{2})_(.+)$", key)
    if not match:
        return None
    resolved_date_iso = match.group(1)
    sport_type = match.group(2)
    if sport_type == "unknown":
        sport_type = None
    value = str(_activity_value(fact, "value") or "")
    duration_match = re.search(r"(\d+)\s*min", value)
    duration_min = int(duration_match.group(1)) if duration_match else None
    return ActivityClaim(
        sport_type=sport_type,
        duration_min=duration_min,
        resolved_date_iso=resolved_date_iso,
        temporal_reference="persisted_claim",
        confidence=float(_activity_value(fact, "confidence") or 0.7),
        source_text=value,
    )


def _non_completion_from_key(key: str) -> tuple[str | None, str | None]:
    match = re.match(r"claimed_non_completion_(\d{4}-\d{2}-\d{2})_(.+)$", key)
    if not match:
        return None, None
    sport_type = match.group(2)
    if sport_type == "unknown":
        sport_type = None
    return match.group(1), sport_type


def _activity_local_date(activity: Any, *, timezone_name: str | None) -> str | None:
    started_at = _activity_value(activity, "started_at") or _activity_value(activity, "created_at")
    if not isinstance(started_at, datetime):
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=get_timezone(timezone_name))
    return started_at.astimezone(get_timezone(timezone_name)).date().isoformat()


def _activity_value(activity: Any, key: str) -> Any:
    if isinstance(activity, dict):
        return activity.get(key)
    return getattr(activity, key, None)


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
