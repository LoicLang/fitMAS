"""Estimate athlete thresholds (VMA, FTP) from Strava activity data.

Heuristics:
- Running: avg_speed * correction_factor → VMA estimate
- Cycling: FTP from power data (future — not in current Strava summary)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.domain.memory.profile_memory import get_active_profile_memory, upsert_profile_memory

logger = logging.getLogger(__name__)

# Correction factors: actual VMA ≈ avg_speed * factor
# Easy runs are much slower than VMA, tempo runs are closer
_INTENSITY_CORRECTION = {
    "easy": 1.35,
    "moderate": 1.15,
    "hard": 1.05,
}

# Minimum thresholds for a meaningful estimate
_MIN_RUNNING_DURATION_MIN = 20
_MIN_RUNNING_SPEED_MS = 1.5   # ~5.4 km/h
_THRESHOLD_DELTA_PCT = 0.05   # 5% change triggers update


def estimate_vma_from_activity(activity: s.Activity) -> float | None:
    """Estimate VMA (km/h) from a running activity.

    Requires: duration > 20min, avg_speed available, sport is running.
    Returns VMA in km/h or None if not estimable.
    """
    if not activity.sport_type or "run" not in activity.sport_type.lower():
        return None
    if not activity.duration_min or activity.duration_min < _MIN_RUNNING_DURATION_MIN:
        return None
    if not activity.avg_speed or activity.avg_speed < _MIN_RUNNING_SPEED_MS:
        return None

    avg_speed_kmh = activity.avg_speed * 3.6

    # Determine intensity bucket from matched session or HR
    intensity = "moderate"  # default
    if activity.avg_hr and activity.max_hr:
        hr_ratio = activity.avg_hr / activity.max_hr
        if hr_ratio < 0.72:
            intensity = "easy"
        elif hr_ratio > 0.85:
            intensity = "hard"

    correction = _INTENSITY_CORRECTION.get(intensity, 1.15)
    vma_estimate = avg_speed_kmh * correction

    # Sanity bounds: 8-25 km/h
    if vma_estimate < 8 or vma_estimate > 25:
        return None

    return round(vma_estimate, 1)


def update_threshold_facts(
    db: Session,
    user: s.User,
    activity: s.Activity,
) -> bool:
    """Check if activity yields a better threshold estimate.

    If the new estimate differs by >5% from current, upsert the fact.
    Returns True if a threshold was updated.
    """
    vma = estimate_vma_from_activity(activity)
    if vma is None:
        return False

    # Get current VMA fact
    current_vma = _get_threshold_fact_value(db, user.id, "vma")

    if current_vma is not None:
        delta = abs(vma - current_vma) / current_vma
        if delta < _THRESHOLD_DELTA_PCT:
            return False
        # Only update if new estimate is higher (conservative — VMA doesn't drop fast)
        if vma < current_vma * 0.90:
            return False

    upsert_profile_memory(db, user.id, [{
        "category": "threshold",
        "key": "vma",
        "value": str(vma),
        "source": "strava_estimated",
        "confidence": 0.6,
        "ttl": "long",
        "urgency": "low",
    }])

    logger.info("VMA threshold updated from Strava: %.1f km/h (was %s)", vma, current_vma)
    return True


def _get_threshold_fact_value(db: Session, user_id: int, key: str) -> float | None:
    """Get current threshold fact value."""
    facts = get_active_profile_memory(db, user_id)
    for fact in facts:
        if fact.category == "threshold" and fact.key == key:
            try:
                return float(fact.value)
            except (ValueError, TypeError):
                return None
    return None
