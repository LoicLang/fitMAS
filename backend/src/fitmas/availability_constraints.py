from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class AvailabilityConstraintKey:
    sport_type: str | None
    start_date: date
    end_date: date


_AVAILABILITY_KEY_RE = re.compile(
    r"^unavailable_(?P<sport>[a-z_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})$"
)


def parse_availability_fact_key(key: str | None) -> AvailabilityConstraintKey | None:
    """Parse the canonical availability memory key.

    This reads a stored DB key, not free user text. It is safe deterministic
    decoding of a machine artifact.
    """
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
