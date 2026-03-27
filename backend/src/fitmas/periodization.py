"""Mesocycle periodization — 3+1 pattern (3 build + 1 recovery).

Tracks where the athlete is in the current mesocycle and provides
progression multipliers for volume, reps, and TSS.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MesocycleState:
    phase: str  # "base", "build", "specialty" (V2: always "build")
    cycle_number: int  # nth mesocycle (1-based)
    week_in_cycle: int  # 1-4
    cycle_length: int  # 4 (3 build + 1 recovery)
    is_recovery_week: bool  # week_in_cycle == cycle_length
    total_weeks: int  # since first plan
    progression_level: float  # 1.0 baseline, +0.05 per build week


# ---------------------------------------------------------------------------
# Progression multipliers
# ---------------------------------------------------------------------------

# Week-in-cycle → (TSS multiplier, volume multiplier, reps multiplier)
_WEEK_PROGRESSION: dict[int, tuple[float, float, float]] = {
    1: (1.00, 1.00, 1.00),  # baseline
    2: (1.05, 1.05, 1.00),  # +5% TSS/volume, reps via RepScaling.cycle_week_delta
    3: (1.08, 1.08, 1.00),  # +8% TSS/volume
    4: (0.65, 0.80, 0.50),  # recovery: -35% TSS, -20% volume, -50% reps
}


def compute_mesocycle_state(
    *,
    total_weeks: int,
    cycle_length: int = 4,
    phase: str = "build",
) -> MesocycleState:
    """Compute mesocycle state from total weeks of training."""
    if total_weeks < 1:
        total_weeks = 1
    cycle_number = ((total_weeks - 1) // cycle_length) + 1
    week_in_cycle = ((total_weeks - 1) % cycle_length) + 1
    is_recovery = week_in_cycle == cycle_length

    # Progression level: +0.05 per build week across all mesocycles
    build_weeks_completed = total_weeks - cycle_number  # subtract recovery weeks
    progression_level = 1.0 + (max(0, build_weeks_completed) * 0.05)

    return MesocycleState(
        phase=phase,
        cycle_number=cycle_number,
        week_in_cycle=week_in_cycle,
        cycle_length=cycle_length,
        is_recovery_week=is_recovery,
        total_weeks=total_weeks,
        progression_level=round(progression_level, 2),
    )


def derive_total_weeks(*, mesocycle_number: int | None, mesocycle_week: int | None, cycle_length: int = 4) -> int:
    cycle_number = max(1, int(mesocycle_number or 1))
    week_in_cycle = max(1, int(mesocycle_week or 1))
    return ((cycle_number - 1) * cycle_length) + week_in_cycle


def get_tss_multiplier(week_in_cycle: int) -> float:
    return _WEEK_PROGRESSION.get(week_in_cycle, (1.0, 1.0, 1.0))[0]


def get_volume_multiplier(week_in_cycle: int) -> float:
    return _WEEK_PROGRESSION.get(week_in_cycle, (1.0, 1.0, 1.0))[1]


def get_reps_multiplier(week_in_cycle: int) -> float:
    return _WEEK_PROGRESSION.get(week_in_cycle, (1.0, 1.0, 1.0))[2]


def should_force_deload(week_in_cycle: int) -> bool:
    """Whether the planning mode should be overridden to deload."""
    return week_in_cycle >= 4


def adjust_planning_mode(current_mode: str, week_in_cycle: int) -> str:
    """Override planning mode based on mesocycle week."""
    if should_force_deload(week_in_cycle):
        return "deload"
    return current_mode
