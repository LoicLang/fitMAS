from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForecastWeek:
    week_index: int
    cycle_week: int
    target_tss: float
    projected_ctl: float
    focus: str
    planning_mode: str
    is_deload: bool


def build_load_forecast(
    *,
    current_ctl: float,
    current_target_tss: float,
    current_cycle_week: int,
    weeks: int = 4,
    planning_mode: str = "maintain_load",
) -> list[ForecastWeek]:
    forecasts: list[ForecastWeek] = []
    projected_ctl = float(current_ctl)
    previous_target = max(float(current_target_tss), 0.0)

    for index in range(weeks):
        cycle_week = ((current_cycle_week - 1 + index) % 4) + 1
        is_deload = cycle_week == 4
        target_tss = _target_for_week(previous_target=previous_target, cycle_week=cycle_week, planning_mode=planning_mode)
        projected_ctl = _project_next_ctl(current_ctl=projected_ctl, weekly_tss=target_tss)
        forecasts.append(
            ForecastWeek(
                week_index=index + 1,
                cycle_week=cycle_week,
                target_tss=round(target_tss, 1),
                projected_ctl=round(projected_ctl, 1),
                focus=_focus_label(cycle_week=cycle_week, planning_mode=planning_mode, is_deload=is_deload),
                planning_mode=planning_mode,
                is_deload=is_deload,
            )
        )
        previous_target = target_tss

    return forecasts


def _target_for_week(*, previous_target: float, cycle_week: int, planning_mode: str) -> float:
    base = max(previous_target, 0.0)
    if cycle_week == 4 or planning_mode in {"deload", "injury_protection"}:
        return base * 0.72

    growth = {
        "increase_load": 1.09,
        "maintain_load": 1.03,
        "reduce_load": 0.92,
    }.get(planning_mode, 1.0)

    if cycle_week == 1:
        return base * max(growth, 0.96)
    if cycle_week == 2:
        return base * max(growth, 1.04)
    return base * max(growth, 1.06)


def _project_next_ctl(*, current_ctl: float, weekly_tss: float) -> float:
    daily_target = weekly_tss / 7.0
    adaptation = 1.0 - math.exp(-7.0 / 42.0)
    return current_ctl + (daily_target - current_ctl) * adaptation


PLANNING_MODE_LABELS_FR = {
    "maintain_load": "Maintien",
    "increase_load": "Construction",
    "reduce_load": "Réduction",
    "deload": "Assimilation",
    "injury_protection": "Protection",
}


def planning_mode_label_fr(mode: str) -> str:
    return PLANNING_MODE_LABELS_FR.get(mode, mode.replace("_", " ").capitalize())


def _focus_label(*, cycle_week: int, planning_mode: str, is_deload: bool) -> str:
    if is_deload:
        return "Assimilation"
    if planning_mode == "increase_load":
        return "Construction"
    if planning_mode == "reduce_load":
        return "Réduction"
    if cycle_week == 3:
        return "Pic contrôlé"
    if cycle_week == 1:
        return "Relance"
    return "Consolidation"
