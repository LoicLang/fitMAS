"""Athlete training zones based on sport-specific thresholds.

Pure computation module — no DB imports. Zones are derived from:
- Running: VMA (km/h) → 5 zones (60-100% VMA)
- Cycling: FTP (watts) → 7 zones (Coggan model)
- Swimming: CSS (sec/100m) → 5 zones
- Heart rate: FCmax (bpm) → Karvonen-based HR zones
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ZoneBand:
    zone: str  # "Z1", "Z2", ..., "Z7"
    label: str  # "Endurance fondamentale", "Seuil", "VO2max"
    low_pct: float  # % of threshold (e.g. 0.60)
    high_pct: float  # % of threshold (e.g. 0.70)
    pace_low: str | None = None  # "6:30/km" (running, slower)
    pace_high: str | None = None  # "5:20/km" (running, faster)
    power_low: int | None = None  # watts (cycling)
    power_high: int | None = None
    css_low: int | None = None  # sec/100m (swimming, slower)
    css_high: int | None = None  # sec/100m (swimming, faster)
    hr_low: int | None = None  # bpm
    hr_high: int | None = None


@dataclass(frozen=True, slots=True)
class AthleteZones:
    vma_kmh: float | None
    fc_max: int | None
    ftp_watts: int | None
    css_per_100m: int | None  # seconds
    running_zones: tuple[ZoneBand, ...]
    cycling_zones: tuple[ZoneBand, ...]
    swimming_zones: tuple[ZoneBand, ...]


# ---------------------------------------------------------------------------
# Level → threshold estimation tables
# ---------------------------------------------------------------------------

_VMA_BY_LEVEL: dict[str, float] = {
    "beginner": 10.0,
    "intermediate": 14.0,
    "advanced": 17.5,
    "unknown": 12.0,
}

_FTP_BY_LEVEL: dict[str, int] = {
    "beginner": 120,
    "intermediate": 200,
    "advanced": 280,
    "unknown": 160,
}

_CSS_BY_LEVEL: dict[str, int] = {
    "beginner": 150,
    "intermediate": 110,
    "advanced": 85,
    "unknown": 130,
}

_FCMAX_DEFAULT = 190

# ---------------------------------------------------------------------------
# Running zones — %VMA based (5 zones, French model)
# ---------------------------------------------------------------------------

_RUNNING_ZONE_DEFS: tuple[tuple[str, str, float, float], ...] = (
    ("Z1", "Endurance fondamentale", 0.60, 0.70),
    ("Z2", "Endurance active", 0.70, 0.80),
    ("Z3", "Tempo / Seuil", 0.80, 0.88),
    ("Z4", "Allure 10k", 0.88, 0.95),
    ("Z5", "VO2max", 0.95, 1.00),
)

# Approximate HR as % of FCmax for each running zone (Karvonen-like)
_RUNNING_HR_PCT: tuple[tuple[float, float], ...] = (
    (0.60, 0.70),  # Z1
    (0.70, 0.80),  # Z2
    (0.80, 0.88),  # Z3
    (0.88, 0.92),  # Z4
    (0.92, 1.00),  # Z5
)

# ---------------------------------------------------------------------------
# Cycling zones — %FTP based (7 zones, Coggan model)
# ---------------------------------------------------------------------------

_CYCLING_ZONE_DEFS: tuple[tuple[str, str, float, float], ...] = (
    ("Z1", "Recuperation", 0.00, 0.55),
    ("Z2", "Endurance", 0.55, 0.75),
    ("Z3", "Tempo", 0.76, 0.87),
    ("Z4", "Sweet Spot", 0.88, 0.94),
    ("Z5", "Seuil", 0.95, 1.05),
    ("Z6", "VO2max", 1.06, 1.20),
    ("Z7", "Anaerobie", 1.21, 1.50),
)

# ---------------------------------------------------------------------------
# Swimming zones — CSS-based (5 zones, pace offset model)
# Slower pace = higher sec/100m value
# ---------------------------------------------------------------------------

_SWIMMING_ZONE_DEFS: tuple[tuple[str, str, float, float], ...] = (
    ("Z1", "Recup", 1.15, 1.25),  # CSS +15% to +25% (slower)
    ("Z2", "Endurance", 1.05, 1.15),  # CSS +5% to +15%
    ("Z3", "Threshold", 0.95, 1.05),  # CSS +/-5%
    ("Z4", "VO2max", 0.90, 0.95),  # CSS -5% to -10% (faster)
    ("Z5", "Sprint", 0.80, 0.90),  # CSS -10% to -20%
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate_vma_from_level(level: str) -> float:
    return _VMA_BY_LEVEL.get(level, _VMA_BY_LEVEL["unknown"])


def estimate_ftp_from_level(level: str) -> int:
    return _FTP_BY_LEVEL.get(level, _FTP_BY_LEVEL["unknown"])


def estimate_css_from_level(level: str) -> int:
    return _CSS_BY_LEVEL.get(level, _CSS_BY_LEVEL["unknown"])


def compute_running_zones(
    vma_kmh: float, fc_max: int | None = None
) -> tuple[ZoneBand, ...]:
    zones: list[ZoneBand] = []
    for i, (zone, label, low_pct, high_pct) in enumerate(_RUNNING_ZONE_DEFS):
        speed_low = vma_kmh * low_pct  # km/h
        speed_high = vma_kmh * high_pct  # km/h
        pace_low = _speed_to_pace(speed_low)  # slower pace
        pace_high = _speed_to_pace(speed_high)  # faster pace
        hr_low = int(fc_max * _RUNNING_HR_PCT[i][0]) if fc_max else None
        hr_high = int(fc_max * _RUNNING_HR_PCT[i][1]) if fc_max else None
        zones.append(
            ZoneBand(
                zone=zone,
                label=label,
                low_pct=low_pct,
                high_pct=high_pct,
                pace_low=pace_low,
                pace_high=pace_high,
                hr_low=hr_low,
                hr_high=hr_high,
            )
        )
    return tuple(zones)


def compute_cycling_zones(ftp_watts: int) -> tuple[ZoneBand, ...]:
    zones: list[ZoneBand] = []
    for zone, label, low_pct, high_pct in _CYCLING_ZONE_DEFS:
        zones.append(
            ZoneBand(
                zone=zone,
                label=label,
                low_pct=low_pct,
                high_pct=high_pct,
                power_low=int(ftp_watts * low_pct),
                power_high=int(ftp_watts * high_pct),
            )
        )
    return tuple(zones)


def compute_swimming_zones(css_per_100m: int) -> tuple[ZoneBand, ...]:
    zones: list[ZoneBand] = []
    for zone, label, low_pct, high_pct in _SWIMMING_ZONE_DEFS:
        # low_pct = faster multiplier (fewer sec), high_pct = slower multiplier (more sec)
        zones.append(
            ZoneBand(
                zone=zone,
                label=label,
                low_pct=low_pct,
                high_pct=high_pct,
                css_low=int(css_per_100m * low_pct),  # faster end (fewer sec)
                css_high=int(css_per_100m * high_pct),  # slower end (more sec)
            )
        )
    return tuple(zones)


def build_athlete_zones(
    profile: object,  # AthleteProfileSnapshot
    facts: Sequence[object],  # s.UserFact
) -> AthleteZones:
    """Build zones from profile + facts. Threshold facts override level estimates."""
    level_by_sport: dict[str, str] = getattr(profile, "level_by_sport", {})
    primary_sports: tuple[str, ...] = getattr(profile, "primary_sports", ("running",))

    # Extract threshold facts
    vma: float | None = None
    fc_max: int | None = None
    ftp: int | None = None
    css: int | None = None

    for fact in facts:
        cat = getattr(fact, "category", "")
        key = getattr(fact, "key", "")
        val = getattr(fact, "value", "")
        if cat != "threshold":
            continue
        try:
            if key == "vma":
                vma = float(val)
            elif key == "fc_max":
                fc_max = int(float(val))
            elif key == "ftp":
                ftp = int(float(val))
            elif key == "css":
                css = int(float(val))
        except (ValueError, TypeError):
            continue

    # Fall back to level-based estimates for sports the user trains
    if vma is None and any(s in primary_sports for s in ("running", "trail")):
        level = level_by_sport.get("running", level_by_sport.get("trail", "unknown"))
        vma = estimate_vma_from_level(level)
    if ftp is None and "cycling" in primary_sports:
        level = level_by_sport.get("cycling", "unknown")
        ftp = estimate_ftp_from_level(level)
    if css is None and "swimming" in primary_sports:
        level = level_by_sport.get("swimming", "unknown")
        css = estimate_css_from_level(level)

    running_zones = compute_running_zones(vma, fc_max) if vma else ()
    cycling_zones = compute_cycling_zones(ftp) if ftp else ()
    swimming_zones = compute_swimming_zones(css) if css else ()

    return AthleteZones(
        vma_kmh=vma,
        fc_max=fc_max,
        ftp_watts=ftp,
        css_per_100m=css,
        running_zones=running_zones,
        cycling_zones=cycling_zones,
        swimming_zones=swimming_zones,
    )


# ---------------------------------------------------------------------------
# Zone formatting for LLM prompts
# ---------------------------------------------------------------------------


def format_zones_for_prompt(zones: AthleteZones) -> str:
    """Format all zones as a concise string for LLM injection."""
    parts: list[str] = []
    if zones.running_zones:
        parts.append(f"Running (VMA {zones.vma_kmh} km/h):")
        for z in zones.running_zones:
            line = f"  {z.zone} {z.label}: {z.pace_low} - {z.pace_high}"
            if z.hr_low and z.hr_high:
                line += f" (FC {z.hr_low}-{z.hr_high})"
            parts.append(line)
    if zones.cycling_zones:
        parts.append(f"Cycling (FTP {zones.ftp_watts}W):")
        for z in zones.cycling_zones:
            parts.append(f"  {z.zone} {z.label}: {z.power_low}-{z.power_high}W")
    if zones.swimming_zones:
        parts.append(f"Swimming (CSS {zones.css_per_100m}s/100m):")
        for z in zones.swimming_zones:
            parts.append(f"  {z.zone} {z.label}: {z.css_low}-{z.css_high}s/100m")
    return "\n".join(parts)


def get_zone_target(zones: AthleteZones, sport: str, zone_name: str) -> ZoneBand | None:
    """Get a specific zone band for a sport."""
    if sport in ("running", "trail"):
        zone_list = zones.running_zones
    elif sport == "cycling":
        zone_list = zones.cycling_zones
    elif sport == "swimming":
        zone_list = zones.swimming_zones
    else:
        return None
    for z in zone_list:
        if z.zone == zone_name:
            return z
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _speed_to_pace(speed_kmh: float) -> str:
    """Convert km/h to min:sec/km pace string."""
    if speed_kmh <= 0:
        return "99:59/km"
    pace_min_total = 60.0 / speed_kmh
    minutes = int(pace_min_total)
    seconds = int((pace_min_total - minutes) * 60)
    return f"{minutes}:{seconds:02d}/km"
