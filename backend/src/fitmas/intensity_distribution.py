"""Polarized intensity distribution (80/20 model, Seiler).

Computes weekly intensity budgets based on planning mode.
Z1-Z2 (low, under LT1) / Z3 (moderate, between LT1-LT2) / Z4-Z5+ (high, above LT2).
Key rule: Z3 "no man's land" should always stay <= 10%.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeekIntensityBudget:
    low_pct: float  # Z1-Z2
    moderate_pct: float  # Z3
    high_pct: float  # Z4-Z5+
    total_duration_min: int
    low_minutes: int
    moderate_minutes: int
    high_minutes: int


# Distribution tables by planning mode (Seiler-based 80/20)
_DISTRIBUTION: dict[str, tuple[float, float, float]] = {
    "increase_load": (0.75, 0.05, 0.20),
    "maintain_load": (0.80, 0.05, 0.15),
    "reduce_load": (0.85, 0.05, 0.10),
    "deload": (0.90, 0.10, 0.00),
    "tactical_adjustment": (0.82, 0.08, 0.10),
    "injury_protection": (1.00, 0.00, 0.00),
}

_DEFAULT_DISTRIBUTION = (0.80, 0.05, 0.15)


def compute_intensity_budget(mode: str, total_duration_min: int) -> WeekIntensityBudget:
    low_pct, mod_pct, high_pct = _DISTRIBUTION.get(mode, _DEFAULT_DISTRIBUTION)
    return WeekIntensityBudget(
        low_pct=low_pct,
        moderate_pct=mod_pct,
        high_pct=high_pct,
        total_duration_min=total_duration_min,
        low_minutes=int(total_duration_min * low_pct),
        moderate_minutes=int(total_duration_min * mod_pct),
        high_minutes=int(total_duration_min * high_pct),
    )


# ---------------------------------------------------------------------------
# Zone classification for sessions
# ---------------------------------------------------------------------------

# Map session target zones to intensity buckets
_ZONE_TO_BUCKET: dict[str, str] = {
    "Z1": "low",
    "Z2": "low",
    "Z3": "moderate",
    "Z4": "high",
    "Z5": "high",
    "Z6": "high",
    "Z7": "high",
}


def classify_session_intensity(target_zone: str) -> str:
    """Classify a session's target zone into low/moderate/high bucket."""
    return _ZONE_TO_BUCKET.get(target_zone, "low")


def check_distribution(
    sessions: list[dict],
    mode: str,
) -> list[str]:
    """Check a week's sessions against the polarized distribution.

    Returns a list of warning strings (empty = OK).
    Sessions should have 'duration_min' and 'target_zone' or 'intensity' keys.
    """
    total_min = 0
    bucket_min: dict[str, int] = {"low": 0, "moderate": 0, "high": 0}

    for session in sessions:
        dur = session.get("duration_min") or 0
        if dur <= 0 or session.get("sport_type") == "rest":
            continue
        total_min += dur
        # Prefer target_zone from blueprint, else infer from intensity
        target_zone = session.get("target_zone", "")
        if target_zone:
            bucket = classify_session_intensity(target_zone)
        else:
            intensity = session.get("intensity", "easy")
            bucket = "high" if intensity == "hard" else "moderate" if intensity == "moderate" else "low"
        bucket_min[bucket] += dur

    if total_min == 0:
        return []

    warnings: list[str] = []
    mod_pct = bucket_min["moderate"] / total_min
    high_pct = bucket_min["high"] / total_min

    if mod_pct > 0.15:
        warnings.append(f"Z3 moderate at {mod_pct:.0%} (target <=10%): too much tempo/threshold work")
    if high_pct > 0.25:
        warnings.append(f"Z4+ high at {high_pct:.0%} (target <=20%): risk of accumulated fatigue")

    budget = compute_intensity_budget(mode, total_min)
    if mode == "deload" and bucket_min["high"] > 0:
        warnings.append("Deload week should have no Z4+ sessions")

    return warnings
