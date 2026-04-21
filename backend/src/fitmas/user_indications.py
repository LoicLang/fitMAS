from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from datetime import timedelta

from fitmas.activity_claims import extract_activity_claim, extract_non_completion_claim
from fitmas.temporal_resolver import TemporalResolution, resolve_temporal_context
from fitmas.time_context import DAY_KEYS

_UNAVAILABLE_PATTERNS = (
    "je peux pas",
    "je ne peux pas",
    "pas possible",
    "pas dispo",
    "indispo",
    "c est mort",
    "c'est mort",
    "imprevu",
    "imprévu",
)
_LIMITED_PATTERNS = (
    "je peux faire court",
    "pas longtemps",
    "juste 20 min",
    "juste 30 min",
    "pas intense",
)
_TRAVEL_PATTERNS = (
    "voyage",
    "travel",
    "deplacement",
    "déplacement",
    "je bouge",
)
_HEALTH_PATTERNS = (
    "j ai mal",
    "j'ai mal",
    "douleur",
    "gêne",
    "gene",
    "ca tire",
    "ça tire",
    "ca coince",
    "ça coince",
    "sensible",
    "tendon",
    "malade",
    "maladie",
    "virus",
    "fievre",
    "fièvre",
    "grippe",
    "creve",
    "crevé",
    "hs",
)
_SEVERE_HEALTH_PATTERNS = (
    "blessure",
    "bloque",
    "bloqué",
    "impossible",
    "vive douleur",
    "aigu",
    "aigue",
    "aiguë",
)
_BODY_ZONE_PATTERNS = {
    "shoulder": ("epaule", "épaule", "deltoide", "deltoïde"),
    "knee": ("genou", "rotule"),
    "achilles": ("achille",),
    "back": ("dos", "lombaire", "lombaires"),
    "hip": ("hanche",),
    "calf": ("mollet", "mollets"),
    "ankle": ("cheville",),
}
_TRIGGER_ACTIVITY_PATTERNS = {
    "swimming": ("nage", "nager", "natation", "piscine"),
    "running": ("course", "courir", "couru", "run", "footing"),
    "cycling": ("velo", "vélo", "bike", "rouler", "roule"),
    "strength": ("muscu", "renfo", "gainage"),
    "climbing": ("escalade", "grimpe", "bloc"),
}
_EXECUTION_PATTERNS = (
    "j ai fait",
    "j'ai fait",
    "j ai couru",
    "j'ai couru",
    "j ai nage",
    "j'ai nagé",
    "j ai roule",
    "j'ai roulé",
    "j ai rien fait",
    "j'ai rien fait",
    "rien fait",
    "pas fait",
)
_SHORT_NEGATIVE_ANSWERS = {"non", "nope", "nan"}
_SHORT_POSITIVE_ANSWERS = {"oui", "ouais", "yes", "ok oui", "si"}
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
        trigger_activity=str(health.get("trigger_activity") or "").strip() or None,
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


def fallback_interpret_user_indication(
    text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
    recent_agent_text: str | None = None,
    clarification_date: date | None = None,
    clarification_sport_type: str | None = None,
) -> UserIndication | None:
    normalized = _normalize(text)
    temporal = resolve_temporal_context(text, timezone_name=timezone_name, now=now)
    clarification_active = looks_like_execution_clarification_prompt(recent_agent_text)

    availability = _fallback_availability_indication(text, normalized=normalized, temporal=temporal)
    if availability is not None:
        return availability

    non_completion = extract_non_completion_claim(
        text,
        timezone_name=timezone_name,
        now=now,
        default_date=clarification_date if clarification_active else None,
        default_sport_type=clarification_sport_type if clarification_active else None,
        allow_contextual_short_answer=clarification_active,
    )
    health = _fallback_health_indication(text, normalized=normalized, temporal=temporal)
    if health is not None:
        if non_completion is not None:
            return _with_execution_resolution(
                health,
                completed=False,
                resolved_date=date.fromisoformat(non_completion.resolved_date_iso) if non_completion.resolved_date_iso else None,
                sport_type=non_completion.sport_type,
            )
        return health

    if non_completion is not None:
        return UserIndication(
            kind=UserIndicationKind.EXECUTION_UPDATE,
            confidence=min(0.95, non_completion.confidence),
            source_text=text.strip(),
            scope=UserIndicationScope.SINGLE_DAY,
            polarity=UserIndicationPolarity.SIGNAL,
            time_reference=IndicationTimeReference(
                label=temporal.primary_reference if temporal.primary_reference != "unspecified" else "clarification",
                resolved_date=date.fromisoformat(non_completion.resolved_date_iso) if non_completion.resolved_date_iso else None,
                day_key=_day_key_from_date(date.fromisoformat(non_completion.resolved_date_iso)) if non_completion.resolved_date_iso else None,
                relative_reference=temporal.primary_reference if temporal.primary_reference != "unspecified" else None,
                window=temporal.part_of_day,
            ),
            execution_sport_type=non_completion.sport_type,
            execution_completed=False,
        )

    claim = extract_activity_claim(text, timezone_name=timezone_name, now=now)
    if claim is not None and (
        any(token in normalized for token in _EXECUTION_PATTERNS)
        or (clarification_active and normalized in _SHORT_POSITIVE_ANSWERS)
    ):
        return UserIndication(
            kind=UserIndicationKind.EXECUTION_UPDATE,
            confidence=min(0.95, claim.confidence),
            source_text=text.strip(),
            scope=UserIndicationScope.SINGLE_DAY,
            polarity=UserIndicationPolarity.SIGNAL,
            time_reference=IndicationTimeReference(
                label=claim.temporal_reference,
                resolved_date=date.fromisoformat(claim.resolved_date_iso) if claim.resolved_date_iso else None,
                day_key=_day_key_from_date(date.fromisoformat(claim.resolved_date_iso)) if claim.resolved_date_iso else None,
                relative_reference=claim.temporal_reference,
                window=temporal.part_of_day,
            ),
            execution_sport_type=claim.sport_type,
            execution_duration_min=claim.duration_min,
            execution_completed=True,
        )
    if clarification_active and normalized in _SHORT_POSITIVE_ANSWERS and clarification_date is not None:
        return UserIndication(
            kind=UserIndicationKind.EXECUTION_UPDATE,
            confidence=0.86,
            source_text=text.strip(),
            scope=UserIndicationScope.SINGLE_DAY,
            polarity=UserIndicationPolarity.SIGNAL,
            time_reference=IndicationTimeReference(
                label="clarification",
                resolved_date=clarification_date,
                day_key=_day_key_from_date(clarification_date),
                relative_reference="yesterday",
                window=temporal.part_of_day,
            ),
            execution_sport_type=clarification_sport_type,
            execution_completed=True,
        )
    return None


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
    # Choisir un label de sport : le pattern trigger ou un fallback générique.
    trigger_activity: str | None = None
    source_text_normalized = _normalize(indication.source_text or "")
    for activity_key, aliases in _TRIGGER_ACTIVITY_PATTERNS.items():
        if any(alias in source_text_normalized for alias in aliases):
            trigger_activity = activity_key
            break
    scope_label = trigger_activity or "general"
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


def _fallback_availability_indication(
    text: str,
    *,
    normalized: str,
    temporal: TemporalResolution,
) -> UserIndication | None:
    if not any(token in normalized for token in _UNAVAILABLE_PATTERNS + _LIMITED_PATTERNS + _TRAVEL_PATTERNS):
        return None
    if temporal.resolved_date is None:
        return None
    scope = UserIndicationScope.SINGLE_WINDOW if temporal.part_of_day else UserIndicationScope.SINGLE_DAY
    if "semaine" in normalized or "plusieurs jours" in normalized:
        scope = UserIndicationScope.WEEK
    polarity = (
        UserIndicationPolarity.LIMITED
        if any(token in normalized for token in _LIMITED_PATTERNS)
        else UserIndicationPolarity.UNAVAILABLE
    )
    confidence = 0.92 if temporal.part_of_day else 0.87
    time_reference = _time_reference_from_temporal(temporal)
    duration_days = _extract_constraint_duration_days(normalized)
    if duration_days is not None and temporal.resolved_date is not None:
        window_end = temporal.resolved_date + timedelta(days=max(0, duration_days - 1))
        time_reference = _with_window_end(time_reference, window_end)
        scope = UserIndicationScope.WEEK
    return UserIndication(
        kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
        confidence=confidence,
        source_text=text.strip(),
        scope=scope,
        polarity=polarity,
        time_reference=time_reference,
        requested_days=_extract_requested_days(normalized),
        earliest_day=_extract_earliest_day(normalized),
    )


# Chantier 4 : patterns pour parser une durée de contrainte multi-jours.
# Matches sur texte normalisé (accents supprimés, lowercase). Le capture
# group `n` donne le nombre ; les bornes basses (`\b`) évitent de matcher
# "12 semaines" sur "12 semainesabc" par exemple.
_DURATION_PATTERNS = (
    # "2 semaines", "pendant 2 semaines", "pour 2 semaines"
    (re.compile(r"\b(?P<n>\d{1,2})\s*semaines?\b"), 7),
    # "15 jours", "pendant 15 jours"
    (re.compile(r"\b(?P<n>\d{1,2})\s*jours?\b"), 1),
    # "une semaine", "la semaine prochaine entiere"
    (re.compile(r"\bune semaine\b"), 7),
    (re.compile(r"\bla semaine\b"), 7),
)


def _extract_constraint_duration_days(normalized: str) -> int | None:
    """Extrait une durée en jours depuis un texte normalisé.

    Retourne None si aucun pattern reconnu. Retourne un `int` quand la
    contrainte porte sur plusieurs jours ("2 semaines" → 14, "15 jours" → 15).
    Utilisé pour calculer `window_end_date` et ancrer `expires_at` sur la
    fin de fenêtre réelle plutôt que sur un TTL fixe."""
    for pattern, multiplier in _DURATION_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        groups = match.groupdict()
        count = 1
        if "n" in groups and groups["n"] is not None:
            try:
                count = max(1, int(groups["n"]))
            except ValueError:
                continue
        days = count * multiplier
        if days >= 2:
            return days
    return None


def _with_window_end(
    time_reference: IndicationTimeReference,
    window_end: date,
) -> IndicationTimeReference:
    return IndicationTimeReference(
        label=time_reference.label,
        resolved_date=time_reference.resolved_date,
        day_key=time_reference.day_key,
        relative_reference=time_reference.relative_reference,
        window=time_reference.window,
        window_end_date=window_end,
    )


def _fallback_health_indication(
    text: str,
    *,
    normalized: str,
    temporal: TemporalResolution,
) -> UserIndication | None:
    if not any(token in normalized for token in _HEALTH_PATTERNS):
        return None
    body_zone = _match_mapping(normalized, _BODY_ZONE_PATTERNS)
    trigger_activity = _match_mapping(normalized, _TRIGGER_ACTIVITY_PATTERNS)
    severity = HealthSeverity.HIGH if any(token in normalized for token in _SEVERE_HEALTH_PATTERNS) else HealthSeverity.MODERATE
    confidence = 0.9 if body_zone or trigger_activity else 0.8
    symptom = "illness" if any(token in normalized for token in ("malade", "maladie", "virus", "fievre", "fièvre", "grippe", "creve", "crevé", "hs")) else ("pain_tightness" if "tire" in normalized else "pain")
    return UserIndication(
        kind=UserIndicationKind.HEALTH_SIGNAL,
        confidence=confidence,
        source_text=text.strip(),
        scope=UserIndicationScope.SINGLE_DAY if temporal.resolved_date else UserIndicationScope.UNKNOWN,
        polarity=UserIndicationPolarity.SIGNAL,
        time_reference=_time_reference_from_temporal(temporal),
        body_zone=body_zone or ("general" if symptom == "illness" else None),
        trigger_activity=trigger_activity or ("general" if symptom == "illness" else None),
        symptom_type=symptom,
        health_severity=severity,
    )


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


def _time_reference_from_temporal(temporal: TemporalResolution) -> IndicationTimeReference:
    return IndicationTimeReference(
        label=_temporal_label(temporal),
        resolved_date=temporal.resolved_date,
        day_key=_day_key_from_date(temporal.resolved_date),
        relative_reference=temporal.primary_reference if temporal.primary_reference != "unspecified" else None,
        window=temporal.part_of_day,
    )


def _temporal_label(temporal: TemporalResolution) -> str:
    if temporal.primary_reference == "tomorrow" and temporal.part_of_day:
        return f"demain {temporal.part_of_day}"
    if temporal.primary_reference == "today" and temporal.part_of_day:
        return f"aujourd'hui {temporal.part_of_day}"
    if temporal.primary_reference != "unspecified":
        return temporal.primary_reference
    if temporal.resolved_date is not None:
        return temporal.resolved_date.isoformat()
    return "reference_inconnue"


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    folded = folded.lower().replace("’", "'")
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _extract_requested_days(normalized: str) -> tuple[str, ...]:
    earliest_spans = _earliest_day_spans(normalized)
    positions: list[tuple[int, str]] = []
    for day_key, aliases in _DAY_ALIASES.items():
        for alias in aliases:
            index = normalized.find(alias)
            if index == -1:
                continue
            if any(start <= index < end for start, end in earliest_spans):
                continue
            positions.append((index, day_key))
            break
    if ("weekend" in normalized or "week end" in normalized) and not any(
        day in {key for _, key in positions} for day in ("saturday", "sunday")
    ):
        weekend_index = normalized.find("weekend")
        if weekend_index == -1:
            weekend_index = normalized.find("week end")
        positions.extend(((weekend_index, "saturday"), (weekend_index + 1, "sunday")))
    ordered: list[str] = []
    for _, day_key in sorted(positions, key=lambda item: item[0]):
        if day_key not in ordered:
            ordered.append(day_key)
    return tuple(ordered)


def _earliest_day_spans(normalized: str) -> list[tuple[int, int]]:
    patterns = (
        r"pas avant (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"a partir de (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"apres (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
    )
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            spans.append(match.span("day"))
    return spans


def _extract_earliest_day(normalized: str) -> str | None:
    for pattern in (
        r"pas avant (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"a partir de (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"apres (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
    ):
        match = re.search(pattern, normalized)
        if not match:
            continue
        token = match.group("day")
        for day_key, aliases in _DAY_ALIASES.items():
            if token in aliases:
                return day_key
    return None


def _match_mapping(text: str, mapping: dict[str, tuple[str, ...]]) -> str | None:
    for key, aliases in mapping.items():
        if any(alias in text for alias in aliases):
            return key
    return None


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


def _with_execution_resolution(
    indication: UserIndication,
    *,
    completed: bool,
    resolved_date: date | None,
    sport_type: str | None,
) -> UserIndication:
    time_reference = indication.time_reference
    if resolved_date is not None and (time_reference is None or time_reference.resolved_date is None):
        time_reference = IndicationTimeReference(
            label="clarification",
            resolved_date=resolved_date,
            day_key=_day_key_from_date(resolved_date),
            relative_reference="yesterday",
            window=time_reference.window if time_reference is not None else None,
        )
    return UserIndication(
        kind=indication.kind,
        confidence=indication.confidence,
        source_text=indication.source_text,
        scope=indication.scope,
        polarity=indication.polarity,
        time_reference=time_reference,
        needs_followup=indication.needs_followup,
        followup_reason=indication.followup_reason,
        body_zone=indication.body_zone,
        trigger_activity=indication.trigger_activity,
        symptom_type=indication.symptom_type,
        health_severity=indication.health_severity,
        execution_sport_type=sport_type or indication.execution_sport_type,
        execution_duration_min=indication.execution_duration_min,
        execution_completed=completed,
    )
