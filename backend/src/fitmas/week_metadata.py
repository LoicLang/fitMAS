from __future__ import annotations

from fitmas.periodization import MesocycleState


def build_week_label(state: MesocycleState) -> str:
    block_label = "Recuperation" if state.is_recovery_week else "Build"
    return f"Semaine {state.week_in_cycle}/{state.cycle_length} · {block_label}"
