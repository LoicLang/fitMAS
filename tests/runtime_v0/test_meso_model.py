from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.model import (
    PlannedWeek,
    TypedSession,
    WeekActuals,
    derive_continuity_target,
)

BASE = date(2026, 6, 8)  # un lundi


def _s(day: int, type: str, duration_min: int, intensity: str) -> TypedSession:
    return TypedSession(
        date=BASE + timedelta(days=day),
        type=type,
        duration_min=duration_min,
        intensity=intensity,
    )


def test_load_weights_by_intensity():
    assert _s(0, "easy_run", 40, "easy").load == 40.0
    assert _s(0, "long_run", 40, "moderate").load == 60.0
    assert _s(0, "threshold", 40, "hard").load == 80.0


def test_rest_load_is_zero():
    assert _s(0, "rest", 0, "easy").load == 0.0


def test_week_load_sums_sessions():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 45, "easy"),     # 45
            _s(2, "threshold", 60, "hard"),    # 120
            _s(6, "long_run", 90, "moderate"),  # 135
        )
    )
    assert week.week_load == 300.0


def test_derived_flags():
    threshold = _s(0, "threshold", 60, "hard")
    assert threshold.is_quality_key is True
    assert threshold.is_hard is True
    assert threshold.is_high_stress is True
    assert threshold.is_impact is True

    long = _s(0, "long_run", 90, "moderate")
    assert long.is_quality_key is False
    assert long.is_hard is False          # volume, pas intensité
    assert long.is_high_stress is True    # stress global inclut le volume
    assert long.is_impact is True

    easy = _s(0, "easy_run", 40, "easy")
    assert easy.is_hard is False
    assert easy.is_high_stress is False
    assert easy.is_impact is True

    rest = _s(0, "rest", 0, "easy")
    assert rest.is_impact is False
    assert rest.is_high_stress is False


def test_derive_continuity_target_build_band():
    target = derive_continuity_target(
        WeekActuals(total_load=380.0, key_type="threshold"), phase="build"
    )
    assert target.phase == "build"
    assert target.key_type == "threshold"          # le type est porté
    assert target.load_band == (380.0, 418.0)       # 100% -> 110%
    assert target.progression_axis == "volume"


def test_derive_continuity_target_recovery_band():
    target = derive_continuity_target(
        WeekActuals(total_load=400.0, key_type="intervals"), phase="recovery"
    )
    assert target.key_type == "intervals"
    assert target.load_band == (200.0, 280.0)        # 50% -> 70%
