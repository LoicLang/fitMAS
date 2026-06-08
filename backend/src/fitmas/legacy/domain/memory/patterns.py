from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from fitmas.legacy.core.time_context import DAY_KEYS, get_local_now

DAY_ALIASES = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}

WINDOW_KEYWORDS = {
    "morning": ("matin", "morning", "7h", "8h", "9h"),
    "midday": ("midi", "midday", "noon", "12h", "13h"),
    "evening": ("soir", "soirée", "soiree", "evening", "18h", "19h", "20h"),
}

UNAVAILABLE_MARKERS = (
    "je peux pas",
    "je ne peux pas",
    "pas dispo",
    "indispo",
    "imprevu",
    "imprévu",
    "c'est mort",
    "c est mort",
    "pas possible",
    "annule",
    "annulé",
    "je saute",
    "je peux plus",
)

LOGISTICS_REASON_CODES = {"logistics_conflict", "travel_constraint"}
MIN_RECURRING_SLOT_EVIDENCE = 3
MIN_PREFERRED_WINDOW_ACTIVITY_COUNT = 4
MIN_PREFERRED_WINDOW_TOTAL = 6
PREFERRED_WINDOW_SHARE = 0.55
LOOKBACK_DAYS = 120


def derive_pattern_payloads(
    *,
    timezone_name: str | None,
    user_messages: Iterable[Any],
    activities: Iterable[Any],
    adaptation_events: Iterable[Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    payloads.extend(
        _derive_recurring_unavailable_slot_patterns(
            timezone_name=timezone_name,
            user_messages=user_messages,
            adaptation_events=adaptation_events,
            now=now,
        )
    )
    payloads.extend(
        _derive_preferred_training_window_patterns(
            timezone_name=timezone_name,
            activities=activities,
            now=now,
        )
    )
    return payloads


def _derive_recurring_unavailable_slot_patterns(
    *,
    timezone_name: str | None,
    user_messages: Iterable[Any],
    adaptation_events: Iterable[Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    today = get_local_now(timezone_name, now=now).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    occurrences: dict[tuple[str, str], dict[tuple[int, int], set[str]]] = defaultdict(lambda: defaultdict(set))

    for message in user_messages:
        if str(_value(message, "role") or "") != "user":
            continue
        created_at = _as_datetime(_value(message, "created_at"))
        if created_at is None:
            continue
        local_date = get_local_now(timezone_name, now=created_at).date()
        if local_date < cutoff:
            continue
        slot = extract_unavailability_slot(
            str(_value(message, "text") or ""),
            timezone_name=timezone_name,
            occurred_at=created_at,
        )
        if slot is None:
            continue
        occurrences[(slot["day"], slot["window"])][_week_key(slot["target_date"])].add("message")

    for event in adaptation_events:
        if str(_value(event, "reason_code") or "") not in LOGISTICS_REASON_CODES:
            continue
        created_at = _as_datetime(_value(event, "created_at"))
        if created_at is None:
            continue
        local_date = get_local_now(timezone_name, now=created_at).date()
        if local_date < cutoff:
            continue
        slot = extract_unavailability_slot(
            str(_value(event, "source_text") or _value(event, "user_message") or ""),
            timezone_name=timezone_name,
            occurred_at=created_at,
        )
        if slot is None:
            continue
        occurrences[(slot["day"], slot["window"])][_week_key(slot["target_date"])].add("adaptation")

    payloads: list[dict[str, Any]] = []
    for (day_key, window), week_sources in occurrences.items():
        evidence_count = len(week_sources)
        if evidence_count < MIN_RECURRING_SLOT_EVIDENCE:
            continue
        confidence = min(0.55 + evidence_count * 0.08, 0.9)
        payloads.append(
            {
                "category": "availability",
                "pattern_type": "recurring_unavailable_slot",
                "key": f"recurring_unavailable_{day_key}_{window}",
                "value": f"{_day_label_fr(day_key)} { _window_label_fr(window) } souvent complique.",
                "source": "maintenance",
                "confidence": round(confidence, 2),
                "confirmed": True,
                "active": True,
                "urgency": "medium",
                "ttl": "long",
                "evidence_count": evidence_count,
                "affects": ["planning", "conversation", "heartbeat"],
                "metadata": {
                    "day": day_key,
                    "window": window,
                    "weeks": evidence_count,
                    "sources": sorted({source for sources in week_sources.values() for source in sources}),
                },
                "first_seen_at": _first_week_datetime(week_sources),
                "last_seen_at": _last_week_datetime(week_sources),
            }
        )
    return payloads


def _derive_preferred_training_window_patterns(
    *,
    timezone_name: str | None,
    activities: Iterable[Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    today = get_local_now(timezone_name, now=now).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    counts: Counter[str] = Counter()

    for activity in activities:
        started_at = _as_datetime(_value(activity, "started_at"))
        if started_at is None:
            continue
        local_started_at = get_local_now(timezone_name, now=started_at)
        if local_started_at.date() < cutoff:
            continue
        counts[_window_from_hour(local_started_at.hour)] += 1

    total = sum(counts.values())
    if total < MIN_PREFERRED_WINDOW_TOTAL:
        return []
    window, count = counts.most_common(1)[0]
    share = count / total if total else 0.0
    if count < MIN_PREFERRED_WINDOW_ACTIVITY_COUNT or share < PREFERRED_WINDOW_SHARE:
        return []
    confidence = min(0.5 + share * 0.45, 0.92)
    return [
        {
            "category": "preference",
            "pattern_type": "preferred_training_window",
            "key": f"preferred_training_window_{window}",
            "value": f"Adherence reelle plus forte { _window_label_fr(window) }.",
            "source": "maintenance",
            "confidence": round(confidence, 2),
            "confirmed": True,
            "active": True,
            "urgency": "low",
            "ttl": "long",
            "evidence_count": count,
            "affects": ["planning", "conversation", "heartbeat"],
            "metadata": {
                "window": window,
                "share": round(share, 2),
                "total_activities": total,
            },
            "first_seen_at": None,
            "last_seen_at": None,
        }
    ]


def extract_unavailability_slot(
    text: str,
    *,
    timezone_name: str | None,
    occurred_at: datetime,
) -> dict[str, Any] | None:
    lowered = (text or "").strip().lower()
    if not lowered or not any(marker in lowered for marker in UNAVAILABLE_MARKERS):
        return None
    window = _extract_window(lowered)
    if window is None:
        return None
    target_date = _resolve_target_date(lowered, timezone_name=timezone_name, occurred_at=occurred_at)
    day_key = DAY_KEYS[target_date.weekday()]
    return {
        "day": day_key,
        "window": window,
        "target_date": target_date,
    }


def _resolve_target_date(text: str, *, timezone_name: str | None, occurred_at: datetime) -> date:
    local_now = get_local_now(timezone_name, now=occurred_at)
    explicit_day = _extract_day_key(text)
    if "demain" in text:
        return local_now.date() + timedelta(days=1)
    if explicit_day is None:
        return local_now.date()
    current_day = local_now.weekday()
    target_day = DAY_KEYS.index(explicit_day)
    delta = (target_day - current_day) % 7
    return local_now.date() + timedelta(days=delta)


def _extract_day_key(text: str) -> str | None:
    for day_key, aliases in DAY_ALIASES.items():
        if any(alias in text for alias in aliases):
            return day_key
    return None


def _extract_window(text: str) -> str | None:
    for window, keywords in WINDOW_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return window
    if "aujourd" in text or "journee" in text or "journée" in text:
        return "day"
    return None


def _window_from_hour(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "midday"
    return "evening"


def _day_label_fr(day_key: str) -> str:
    labels = {
        "monday": "Lundi",
        "tuesday": "Mardi",
        "wednesday": "Mercredi",
        "thursday": "Jeudi",
        "friday": "Vendredi",
        "saturday": "Samedi",
        "sunday": "Dimanche",
    }
    return labels.get(day_key, day_key)


def _window_label_fr(window: str) -> str:
    labels = {
        "morning": "matin",
        "midday": "midi",
        "evening": "soir",
        "day": "en journee",
    }
    return labels.get(window, window)


def _week_key(target_date: date) -> tuple[int, int]:
    iso = target_date.isocalendar()
    return (iso.year, iso.week)


def _first_week_datetime(week_sources: dict[tuple[int, int], set[str]]) -> datetime | None:
    if not week_sources:
        return None
    year, week = min(week_sources.keys())
    return datetime.fromisocalendar(year, week, 1)


def _last_week_datetime(week_sources: dict[tuple[int, int], set[str]]) -> datetime | None:
    if not week_sources:
        return None
    year, week = max(week_sources.keys())
    return datetime.fromisocalendar(year, week, 1)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
