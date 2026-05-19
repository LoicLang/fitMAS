from __future__ import annotations

from datetime import date
from typing import Any

from fitmas.plan_patch import PlanPatch


def summarize_plan_patch_for_user(patch: PlanPatch) -> str | None:
    operations = tuple(getattr(patch, "operations", ()) or ())
    if not operations:
        return None
    if all(str(getattr(operation, "operation_type", "") or "") == "move_session" for operation in operations):
        return _summarize_move_operations(operations)
    return None


def _summarize_move_operations(operations: tuple[Any, ...]) -> str | None:
    target_dates = tuple(
        _date_label(str(getattr(operation, "target_date", "") or "").strip())
        for operation in operations
        if str(getattr(operation, "target_date", "") or "").strip()
    )
    if len(target_dates) != len(operations):
        return None
    if len(operations) == 1:
        return f"deplacer la seance ciblee au {target_dates[0]}"
    return (
        f"deplacer les {len(operations)} seances touchees apres la fenetre, "
        f"en gardant leur ordre: {_joined_dates(target_dates)}"
    )


def _joined_dates(values: tuple[str, ...]) -> str:
    if len(values) <= 1:
        return "".join(values)
    return f"{', '.join(values[:-1])}, puis {values[-1]}"


def _date_label(raw: str) -> str:
    try:
        parsed = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return raw
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return f"{parsed.isoformat()} ({days[parsed.weekday()]})"
