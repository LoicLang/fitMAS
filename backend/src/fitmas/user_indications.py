from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from fitmas.temporal_resolver import resolve_temporal_context
from fitmas.time_context import DAY_KEYS

_DAY_ALIASES = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}


class UserIndicationKind(StrEnum):
    AVAILABILITY_CONSTRAINT = "availability_constraint"
    HEALTH_SIGNAL = "health_signal"
    EXECUTION_UPDATE = "execution_update"
    NONE = "none"


class UserIndicationScope(StrEnum):
    SINGLE_WINDOW = "single_window"
    SINGLE_DAY = "single_day"
    WEEK = "week"
    UNKNOWN = "unknown"


class UserIndicationPolarity(StrEnum):
    UNAVAILABLE = "unavailable"
    LIMITED = "limited"
    SIGNAL = "signal"


class HealthSeverity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class IndicationTimeReference:
    label: str
    resolved_date: date | None
    day_key: str | None
    relative_reference: str | None
    window: str | None  # part-of-day ("morning", "evening"), NOT constraint duration
    # Chantier 4 (mémoire contraintes temporelles): fin inclusive de la
    # fenêtre d'indisponibilité. None quand l'indication couvre un jour
    # unique ou une partie de jour ; posée à la date de fin quand l'user
    # annonce une contrainte multi-jours ("piscine fermée 2 semaines").
    window_end_date: date | None = None


@dataclass(frozen=True, slots=True)
class UserIndication:
    kind: UserIndicationKind
    confidence: float
    source_text: str
    scope: UserIndicationScope
    polarity: UserIndicationPolarity | None = None
    time_reference: IndicationTimeReference | None = None
    needs_followup: bool = False
    followup_reason: str | None = None
    body_zone: str | None = None
    trigger_activity: str | None = None
    symptom_type: str | None = None
    health_severity: HealthSeverity | None = None
    execution_sport_type: str | None = None
    execution_duration_min: int | None = None
    execution_completed: bool | None = None
    requested_days: tuple[str, ...] = ()
    earliest_day: str | None = None


def indication_from_payload(
    payload: dict[str, Any] | None,
    *,
    source_text: str,
    timezone_name: str | None,
    now: datetime | None = None,
) -> UserIndication | None:
    if not isinstance(payload, dict):
        return None
    try:
        kind = UserIndicationKind(str(payload.get("kind") or UserIndicationKind.NONE.value))
    except ValueError:
        return None
    if kind is UserIndicationKind.NONE:
        return None
    try:
        scope = UserIndicationScope(str(payload.get("scope") or UserIndicationScope.UNKNOWN.value))
    except ValueError:
        scope = UserIndicationScope.UNKNOWN
    polarity_value = str(payload.get("polarity") or "").strip()
    polarity = None
    if polarity_value:
        try:
            polarity = UserIndicationPolarity(polarity_value)
        except ValueError:
            polarity = None
    time_reference = _time_reference_from_payload(payload.get("time_reference"), timezone_name=timezone_name, now=now)
    availability = dict(payload.get("availability") or {})
    health = dict(payload.get("health") or {})
    execution = dict(payload.get("execution") or {})
    severity = None
    severity_value = str(health.get("severity") or "").strip()
    if severity_value:
        try:
            severity = HealthSeverity(severity_value)
        except ValueError:
            severity = None
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return UserIndication(
        kind=kind,
        confidence=max(0.0, min(1.0, confidence)),
        source_text=source_text.strip(),
        scope=scope,
        polarity=polarity,
        time_reference=time_reference,
        needs_followup=bool(payload.get("followup_needed", False)),
        followup_reason=str(payload.get("followup_reason") or "").strip() or None,
        body_zone=str(health.get("body_zone") or "").strip() or None,
        trigger_activity=(
            str(availability.get("trigger_activity") or health.get("trigger_activity") or payload.get("trigger_activity") or "").strip()
            or None
        ),
        symptom_type=str(health.get("symptom_type") or "").strip() or None,
        health_severity=severity,
        execution_sport_type=str(execution.get("sport_type") or "").strip() or None,
        execution_duration_min=_coerce_int(execution.get("duration_min")),
        execution_completed=_coerce_execution_completed(execution.get("status")),
        requested_days=tuple(
            day for day in (
                str(item).strip() for item in (payload.get("requested_days") or [])
            )
            if day in _DAY_ALIASES
        ),
        earliest_day=(str(payload.get("earliest_day") or "").strip() or None),
    )


def should_attempt_indication_interpretation(text: str) -> bool:
    return bool((text or "").strip())


def supports_planning_resolution(indication: UserIndication | None) -> bool:
    if indication is None:
        return False
    if indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return False
    return indication.time_reference is not None and indication.time_reference.resolved_date is not None


def build_availability_fact_payloads_from_indication(
    indication: UserIndication | None,
) -> list[dict[str, Any]]:
    """Chantier 4 : transforme une `AVAILABILITY_CONSTRAINT` multi-jours en
    `UserFact` persistante avec `expires_at` ancré sur la fin de fenêtre.

    Ne produit rien quand la contrainte est mono-jour (géré via les flows
    existants de reprogrammation), ni quand la fin de fenêtre est absente
    (on ne veut pas synthétiser un `expires_at` arbitraire qui pollue la
    lecture 3 semaines plus tard).

    Retourne au plus un payload. La clé `unavailable_<activity>_<start>_<end>`
    garantit l'idempotence : si l'user répète "piscine fermée 2 semaines" sur
    la même période, on upsert le même fact."""
    if indication is None or indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return []
    if indication.polarity is not UserIndicationPolarity.UNAVAILABLE:
        return []
    time_reference = indication.time_reference
    if time_reference is None:
        return []
    start = time_reference.resolved_date
    end = time_reference.window_end_date
    if start is None or end is None:
        return []
    if end < start:
        return []
    scope_label = indication.trigger_activity or "general"
    value_text = (
        f"Indispo {scope_label} du {start.isoformat()} au {end.isoformat()} "
        f"(source: {indication.source_text.strip()})"
    )
    return [
        {
            "category": "availability",
            "key": f"unavailable_{scope_label}_{start.isoformat()}_{end.isoformat()}",
            "value": value_text,
            "source": "conversation",
            "confidence": indication.confidence,
            "confirmed": True,
            "affects": ["planning", "conversation", "heartbeat"],
            # `expires_at` posé à la fin du jour de fin : la contrainte reste
            # active tout le dernier jour. `fact_is_current` gère l'UTC ;
            # on passe un datetime naïf minuit-fin-de-jour comme les autres
            # call sites (normalize_fact_payload normalisera si besoin).
            "expires_at": datetime.combine(
                end + timedelta(days=1), datetime.min.time()
            ),
        }
    ]


@dataclass(frozen=True, slots=True)
class AvailabilityConstraintKey:
    sport_type: str | None
    start_date: date
    end_date: date


_AVAILABILITY_KEY_RE = re.compile(
    r"^unavailable_(?P<sport>[a-z_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})$"
)


def parse_availability_fact_key(key: str | None) -> AvailabilityConstraintKey | None:
    """Inverse de `build_availability_fact_payloads_from_indication` : extrait
    sport + fenêtre depuis la clé canonique. Utilisé par
    `_targeted_execution_clarification` pour décider si une séance d'hier
    tombe dans une indisponibilité active."""
    if not key:
        return None
    match = _AVAILABILITY_KEY_RE.match(key)
    if match is None:
        return None
    sport = match.group("sport")
    if sport == "general":
        sport = None
    try:
        start = date.fromisoformat(match.group("start"))
        end = date.fromisoformat(match.group("end"))
    except ValueError:
        return None
    if end < start:
        return None
    return AvailabilityConstraintKey(sport_type=sport, start_date=start, end_date=end)


def build_health_fact_payloads_from_indication(indication: UserIndication | None) -> list[dict[str, Any]]:
    if indication is None or indication.kind is not UserIndicationKind.HEALTH_SIGNAL:
        return []
    body_zone = indication.body_zone or "general"
    trigger_activity = indication.trigger_activity or "general"
    symptom = indication.symptom_type or "pain"
    severity = (indication.health_severity or HealthSeverity.MODERATE).value
    if symptom == "illness":
        value_parts = ["Etat de sante general degrade"]
    else:
        value_parts = ["Douleur"]
    if body_zone != "general":
        value_parts.append(f"a la zone {body_zone}")
    if trigger_activity != "general":
        value_parts.append(f"quand il fait {trigger_activity}")
    if symptom:
        value_parts.append(f"type {symptom}")
    value_parts.append(f"severite {severity}")
    if indication.source_text:
        value_parts.append(f"source: {indication.source_text.strip()}")
    return [
        {
            "category": "health",
            "key": f"reported_health_{body_zone}_{trigger_activity}",
            "value": ". ".join(value_parts) + ".",
            "source": "conversation",
            "confidence": indication.confidence,
            "confirmed": True,
            "affects": ["planning", "conversation", "heartbeat"],
        }
    ]


def _time_reference_from_payload(
    payload: Any,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> IndicationTimeReference | None:
    if not isinstance(payload, dict):
        return None
    label = str(payload.get("label") or "").strip()
    resolved_date = _coerce_date(payload.get("resolved_date"))
    day_key = str(payload.get("day_key") or "").strip() or None
    relative_reference = str(payload.get("relative_reference") or "").strip() or None
    window = str(payload.get("window") or "").strip() or None
    window_end_date = _coerce_date(payload.get("window_end_date"))
    if resolved_date is None and (label or relative_reference):
        temporal = resolve_temporal_context(label or relative_reference or "", timezone_name=timezone_name, now=now)
        resolved_date = temporal.resolved_date
        day_key = day_key or _day_key_from_date(temporal.resolved_date)
        if window is None:
            window = temporal.part_of_day
    if resolved_date is None and day_key in DAY_KEYS:
        temporal = resolve_temporal_context(day_key, timezone_name=timezone_name, now=now)
        resolved_date = temporal.resolved_date
    if resolved_date is not None and day_key is None:
        day_key = _day_key_from_date(resolved_date)
    if not label:
        label = relative_reference or day_key or "reference_inconnue"
    return IndicationTimeReference(
        label=label,
        resolved_date=resolved_date,
        day_key=day_key,
        relative_reference=relative_reference,
        window=window,
        window_end_date=window_end_date,
    )


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    folded = folded.lower().replace("’", "'")
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _day_key_from_date(value: date | None) -> str | None:
    if value is None:
        return None
    return DAY_KEYS[value.weekday()]


def _coerce_execution_completed(value: Any) -> bool | None:
    normalized = str(value or "").strip().lower()
    if normalized == "done":
        return True
    if normalized == "not_done":
        return False
    return None


def looks_like_execution_clarification_prompt(text: str | None) -> bool:
    normalized = _normalize(text or "")
    return (
        "tu l as faite ou non" in normalized
        or "tu l'as faite ou non" in normalized
        or "tu l as faite ou pas" in normalized
        or "tu l'as faite ou pas" in normalized
    )
