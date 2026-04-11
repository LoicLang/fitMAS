from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from fitmas.time_context import DAY_KEYS, build_time_context, get_local_now

DAY_ALIASES = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}


@dataclass(frozen=True, slots=True)
class TemporalResolution:
    local_now_iso: str
    local_date: date
    primary_reference: str
    resolved_date: date | None
    part_of_day: str | None
    explicit_day_key: str | None
    explicit_day_matches_resolved_date: bool | None
    references: tuple[str, ...]


def resolve_temporal_context(
    text: str,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> TemporalResolution:
    local_now = get_local_now(timezone_name, now=now)
    lowered = text.lower()
    references: list[str] = []
    resolved_date: date | None = None
    part_of_day: str | None = None
    explicit_day_key: str | None = None

    if any(token in lowered for token in ("aujourd'hui", "ce matin", "cet aprem", "cet aprèm", "ce soir", "dans la journee")):
        references.append("today")
        resolved_date = local_now.date()
    if "demain matin" in lowered:
        references.append("tomorrow_morning")
        resolved_date = local_now.date() + timedelta(days=1)
        part_of_day = "morning"
    elif any(token in lowered for token in ("demain", "tomorrow")):
        references.append("tomorrow")
        resolved_date = local_now.date() + timedelta(days=1)
    if any(token in lowered for token in ("hier", "yesterday")):
        references.append("yesterday")
        resolved_date = local_now.date() - timedelta(days=1)

    if part_of_day is None:
        if any(token in lowered for token in ("ce matin", "matin", "morning")):
            part_of_day = "morning"
        elif any(token in lowered for token in ("ce soir", "soir", "evening", "tonight")):
            part_of_day = "evening"
        elif any(token in lowered for token in ("midi", "midday", "noon")):
            part_of_day = "midday"

    if resolved_date is None:
        explicit_day_key = _extract_explicit_day(lowered)
        if explicit_day_key is not None:
            references.append(f"explicit_{explicit_day_key}")
            resolved_date = _resolve_day_key(explicit_day_key, local_now.date())
    else:
        explicit_day_key = _extract_explicit_day(lowered)
        if explicit_day_key is not None:
            references.append(f"explicit_{explicit_day_key}")

    primary_reference = references[0] if references else "unspecified"
    explicit_day_matches_resolved_date = None
    if explicit_day_key is not None and resolved_date is not None:
        explicit_day_matches_resolved_date = DAY_KEYS[resolved_date.weekday()] == explicit_day_key
    return TemporalResolution(
        local_now_iso=local_now.isoformat(timespec="minutes"),
        local_date=local_now.date(),
        primary_reference=primary_reference,
        resolved_date=resolved_date,
        part_of_day=part_of_day,
        explicit_day_key=explicit_day_key,
        explicit_day_matches_resolved_date=explicit_day_matches_resolved_date,
        references=tuple(references),
    )


def format_temporal_resolution_for_prompt(resolution: TemporalResolution) -> str:
    resolved_date = resolution.resolved_date.isoformat() if resolution.resolved_date else "unknown"
    refs = ", ".join(resolution.references) or "none"
    return (
        "Resolution temporelle du message:\n"
        f"- local_now: {resolution.local_now_iso}\n"
        f"- date locale de reference: {resolution.local_date.isoformat()}\n"
        f"- reference principale: {resolution.primary_reference}\n"
        f"- date resolue: {resolved_date}\n"
        f"- moment vise: {resolution.part_of_day or 'unspecified'}\n"
        f"- jour explicite detecte: {resolution.explicit_day_key or 'none'}\n"
        f"- jour explicite coherent avec la date resolue: {resolution.explicit_day_matches_resolved_date if resolution.explicit_day_matches_resolved_date is not None else 'unknown'}\n"
        f"- references detectees: {refs}\n"
    )


def _extract_explicit_day(lowered: str) -> str | None:
    for day_key, aliases in DAY_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return day_key
    return None


def _resolve_day_key(day_key: str, local_date: date) -> date:
    current_key = DAY_KEYS[local_date.weekday()]
    current_index = DAY_KEYS.index(current_key)
    target_index = DAY_KEYS.index(day_key)
    delta = target_index - current_index
    if delta < 0:
        delta += 7
    return local_date + timedelta(days=delta)
