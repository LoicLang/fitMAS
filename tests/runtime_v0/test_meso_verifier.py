from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.model import (
    PlannedWeek,
    TypedConstraint,
    TypedSession,
    WeekTarget,
)
from fitmas.runtime_v0.meso.verifier import verify_week

BASE = date(2026, 6, 8)  # un lundi


def _s(day: int, type: str, duration_min: int, intensity: str) -> TypedSession:
    return TypedSession(
        date=BASE + timedelta(days=day),
        type=type,
        duration_min=duration_min,
        intensity=intensity,
    )


def _target(
    band: tuple[float, float] = (350.0, 430.0),
    key_type: str = "threshold",
    phase: str = "build",
) -> WeekTarget:
    return WeekTarget(phase=phase, key_type=key_type, load_band=band)


def _healthy_week() -> PlannedWeek:
    # load = 45 + 120 + 40 + 50 + 135 = 390, dans la bande (350, 430)
    return PlannedWeek(
        sessions=(
            _s(0, "rest", 0, "easy"),
            _s(1, "easy_run", 45, "easy"),
            _s(2, "threshold", 60, "hard"),
            _s(3, "easy_run", 40, "easy"),
            _s(5, "easy_run", 50, "easy"),
            _s(6, "long_run", 90, "moderate"),
        )
    )


def _codes(verdict) -> set[str]:
    return {v.code for v in verdict.violations}


def test_healthy_build_week_passes():
    verdict = verify_week(_healthy_week(), _target())
    assert verdict.ok is True
    assert verdict.violations == ()
    assert verdict.requires_pending is True


def test_key_type_drift_is_caught():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 45, "easy"),
            _s(2, "intervals", 60, "hard"),  # devrait être threshold
            _s(3, "easy_run", 40, "easy"),
            _s(5, "easy_run", 50, "easy"),
            _s(6, "long_run", 90, "moderate"),
        )
    )
    verdict = verify_week(week, _target(key_type="threshold"))
    assert verdict.ok is False
    assert "key_type_drift" in _codes(verdict)
    drift = next(v for v in verdict.violations if v.code == "key_type_drift")
    assert drift.severity == "high"


def test_tss_drop_is_caught():
    # Le cas app : en build, la charge s'effondre vs la bande.
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 30, "easy"),    # 30
            _s(2, "threshold", 30, "hard"),   # 60
            _s(3, "easy_run", 30, "easy"),    # 30
            _s(6, "long_run", 40, "moderate"),  # 60
        )
    )  # load = 180 < 350
    verdict = verify_week(week, _target())
    assert verdict.ok is False
    assert _codes(verdict) == {"load_drop"}
    drop = verdict.violations[0]
    assert drop.severity == "high"


def test_load_spike_is_caught():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 60, "easy"),     # 60
            _s(2, "threshold", 90, "hard"),    # 180
            _s(3, "easy_run", 60, "easy"),     # 60
            _s(5, "easy_run", 40, "easy"),     # 40
            _s(6, "long_run", 110, "moderate"),  # 165
        )
    )  # load = 505 > 430
    verdict = verify_week(week, _target())
    assert _codes(verdict) == {"load_spike"}


def test_two_high_stress_adjacent_is_caught():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 60, "easy"),
            _s(2, "easy_run", 60, "easy"),
            _s(5, "threshold", 60, "hard"),    # samedi, high stress
            _s(6, "long_run", 90, "moderate"),  # dimanche, high stress -> collé
        )
    )  # load = 375 dans la bande
    verdict = verify_week(week, _target())
    assert _codes(verdict) == {"hard_back_to_back"}


def test_zero_quality_session_is_caught():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 90, "easy"),
            _s(2, "easy_run", 90, "easy"),
            _s(5, "easy_run", 60, "easy"),
            _s(6, "long_run", 90, "moderate"),
        )
    )  # load = 375, aucune séance qualité
    verdict = verify_week(week, _target())
    assert _codes(verdict) == {"key_session_count"}


def test_two_quality_sessions_is_caught():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 60, "easy"),
            _s(2, "threshold", 60, "hard"),
            _s(4, "intervals", 60, "hard"),
            _s(6, "long_run", 60, "moderate"),
        )
    )  # deux séances qualité
    verdict = verify_week(week, _target())
    assert "key_session_count" in _codes(verdict)


def test_health_conflict_severe_impact():
    constraint = TypedConstraint(severity="severe", restricts=("impact",), active=True)
    verdict = verify_week(_healthy_week(), _target(), constraints=(constraint,))
    assert verdict.ok is False
    conflict = next(v for v in verdict.violations if v.code == "health_conflict")
    assert conflict.severity == "high"


def test_resolved_health_constraint_does_not_conflict():
    constraint = TypedConstraint(severity="severe", restricts=("impact",), active=False)
    verdict = verify_week(_healthy_week(), _target(), constraints=(constraint,))
    assert verdict.ok is True
    assert "health_conflict" not in _codes(verdict)


def test_transition_mode_allows_load_drop():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 30, "easy"),
            _s(2, "threshold", 30, "hard"),
            _s(3, "easy_run", 30, "easy"),
            _s(6, "long_run", 40, "moderate"),
        )
    )  # load = 180, sous la bande
    verdict = verify_week(week, _target(), mode="transition")
    assert "load_drop" not in _codes(verdict)
    assert verdict.ok is True


def test_transition_mode_flags_unsafe_jump():
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 60, "easy"),
            _s(2, "threshold", 90, "hard"),
            _s(3, "easy_run", 60, "easy"),
            _s(5, "easy_run", 40, "easy"),
            _s(6, "long_run", 110, "moderate"),
        )
    )  # load = 505 > plafond sécurité 430
    verdict = verify_week(week, _target(), mode="transition")
    assert "unsafe_jump" in _codes(verdict)
    jump = next(v for v in verdict.violations if v.code == "unsafe_jump")
    assert jump.severity == "high"


def test_active_intensity_constraint_relaxes_load_drop_and_key():
    # A low, key-less week is legitimate under an active intensity restriction:
    # load_drop + key checks are relaxed; nothing hard -> no health_conflict.
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"), _s(3, "easy_run", 30, "easy")))
    constraint = TypedConstraint(severity="moderate", restricts=("intensity",), active=True)
    verdict = verify_week(week, target, (constraint,))
    assert verdict.ok
    assert verdict.requires_pending is True


def test_low_keyless_week_without_constraint_fails():
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"), _s(3, "easy_run", 30, "easy")))
    verdict = verify_week(week, target)
    codes = {v.code for v in verdict.violations}
    assert "load_drop" in codes
    assert "key_session_count" in codes


def test_inactive_constraint_does_not_relax():
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"),))
    constraint = TypedConstraint(severity="moderate", restricts=("intensity",), active=False)
    verdict = verify_week(week, target, (constraint,))
    assert "load_drop" in {v.code for v in verdict.violations}


def test_empty_week_rejected_even_under_relaxed_constraint():
    # Under an intensity restriction the key + load-floor checks are relaxed, so the
    # structural floor must still reject a degenerate (empty / all-rest) week.
    constraint = (TypedConstraint(severity="moderate", restricts=("intensity",), active=True),)
    empty = PlannedWeek(sessions=())
    verdict = verify_week(empty, _target(), constraint, "continuity")
    assert not verdict.ok
    assert "empty_week" in _codes(verdict)

    all_rest = PlannedWeek(sessions=(_s(0, "rest", 0, "easy"), _s(3, "rest", 0, "easy")))
    assert "empty_week" in _codes(verify_week(all_rest, _target(), constraint, "continuity"))


def test_reduced_constraint_week_still_passes_after_non_empty_check():
    # A real reduced week under the constraint (easy volume only) stays valid: it is
    # non-empty, key check relaxed, no health conflict.
    constraint = (TypedConstraint(severity="moderate", restricts=("intensity",), active=True),)
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 40, "easy"),
            _s(3, "easy_run", 35, "easy"),
            _s(6, "long_run", 60, "moderate"),
        )
    )  # load = 40 + 35 + 90 = 165, in a generous band
    verdict = verify_week(week, _target(band=(50.0, 250.0)), constraint, "continuity")
    assert verdict.ok, _codes(verdict)


# --- Availability / blocked_days tests ---

def test_blocked_day_session_rejected():
    # Wednesday (day=2 from BASE=Monday) is blocked; a training session on it must fail.
    # _GOOD_WEEK-style week but with a training session on Wed (day 2).
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 45, "easy"),        # Tue
            _s(2, "threshold", 60, "hard"),        # Wed — BLOCKED
            _s(4, "easy_run", 40, "easy"),         # Fri
            _s(6, "long_run", 90, "moderate"),     # Sun
        )
    )  # load within band (350, 430): 45 + 120 + 40 + 135 = 340 — use a wider band
    constraint = TypedConstraint(
        severity="moderate", restricts=(), active=True, blocked_days=("wednesday",)
    )
    target = _target(band=(200.0, 500.0), key_type="threshold")
    verdict = verify_week(week, target, constraints=(constraint,))
    assert verdict.ok is False
    assert "blocked_day_session" in _codes(verdict)


def test_week_avoiding_blocked_days_ok():
    # Same constraint but all training sessions on non-blocked days: no blocked_day_session.
    week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 45, "easy"),         # Tue — ok
            _s(3, "threshold", 60, "hard"),        # Thu — ok
            _s(4, "easy_run", 40, "easy"),         # Fri — ok
            _s(6, "long_run", 90, "moderate"),     # Sun — ok
        )
    )
    constraint = TypedConstraint(
        severity="moderate", restricts=(), active=True, blocked_days=("wednesday",)
    )
    target = _target(band=(200.0, 500.0), key_type="threshold")
    verdict = verify_week(week, target, constraints=(constraint,))
    assert "blocked_day_session" not in _codes(verdict)


def test_blocked_days_relax_load_floor():
    # A below-band-load week WITH a blocked-days constraint → no load_drop.
    # The same week WITHOUT the constraint → load_drop fires.
    target = _target(band=(300.0, 330.0), key_type="threshold")
    low_week = PlannedWeek(
        sessions=(
            _s(1, "threshold", 50, "hard"),    # 100 — key present
            _s(3, "easy_run", 30, "easy"),     # 30
        )
    )  # load = 130 < 300 (well below floor)
    constraint = TypedConstraint(
        severity="moderate", restricts=(), active=True, blocked_days=("wednesday", "thursday", "friday", "saturday", "sunday")
    )
    verdict_with = verify_week(low_week, target, constraints=(constraint,))
    assert "load_drop" not in _codes(verdict_with), "blocked_days should relax load floor"

    verdict_without = verify_week(low_week, target, constraints=())
    assert "load_drop" in _codes(verdict_without), "without constraint load_drop must fire"


def test_blocked_days_keep_key_requirement():
    # Pure availability constraint (restricts=(), blocked_days set) — build phase.
    # A week missing the prescribed key must still raise a key violation
    # (availability alone does NOT drop the key; only intensity restriction does).
    target = _target(band=(200.0, 500.0), key_type="threshold")
    no_key_week = PlannedWeek(
        sessions=(
            _s(1, "easy_run", 90, "easy"),     # Mon
            _s(3, "easy_run", 80, "easy"),     # Wed — but this day is NOT blocked
            _s(5, "easy_run", 60, "easy"),     # Fri
            _s(6, "long_run", 80, "moderate"), # Sat
        )
    )  # no threshold/intervals key session
    constraint = TypedConstraint(
        severity="moderate", restricts=(), active=True, blocked_days=("tuesday",)
    )
    verdict = verify_week(no_key_week, target, constraints=(constraint,))
    assert "key_session_count" in _codes(verdict) or "key_type_drift" in _codes(verdict), (
        "availability constraint must not drop the key requirement"
    )
