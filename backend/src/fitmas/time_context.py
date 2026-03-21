from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Paris"

DAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

DAY_LABELS_FR = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
    "sunday": "dimanche",
}

MONTH_LABELS_FR = {
    1: "janvier",
    2: "fevrier",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "aout",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "decembre",
}


def get_timezone(timezone_name: str | None) -> ZoneInfo:
    candidate = (timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def get_local_now(timezone_name: str | None, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(get_timezone(timezone_name))


def build_time_context(timezone_name: str | None, *, now: datetime | None = None) -> dict[str, str]:
    local_now = get_local_now(timezone_name, now=now)
    day_key = DAY_KEYS[local_now.weekday()]
    return {
        "timezone": getattr(local_now.tzinfo, "key", None) or timezone_name or DEFAULT_TIMEZONE,
        "now_iso": local_now.isoformat(timespec="minutes"),
        "date_fr": f"{local_now.day} {MONTH_LABELS_FR[local_now.month]} {local_now.year}",
        "time_fr": local_now.strftime("%H:%M"),
        "day_key": day_key,
        "day_label_fr": DAY_LABELS_FR[day_key],
        "part_of_day": _part_of_day(local_now.hour),
    }


def render_time_context(time_context: dict[str, str]) -> str:
    return (
        "Contexte temporel exact:\n"
        f"- timezone user: {time_context['timezone']}\n"
        f"- maintenant local: {time_context['day_label_fr']} {time_context['date_fr']} a {time_context['time_fr']}\n"
        f"- now_iso: {time_context['now_iso']}\n"
        f"- aujourd'hui: {time_context['day_key']}\n"
        f"- moment de la journee: {time_context['part_of_day']}\n"
        "Interprete toujours aujourd'hui, demain, hier, ce soir et demain matin a partir de ce contexte.\n"
    )


def _part_of_day(hour: int) -> str:
    if hour < 5:
        return "nuit"
    if hour < 12:
        return "matin"
    if hour < 18:
        return "apres-midi"
    return "soir"
