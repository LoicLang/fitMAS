from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fitmas.session_templates import render_session_description, select_session_template
from fitmas.strength_engine import build_strength_workout

_SYSTEM_MARKERS = (
    "clawcoach",
    "session_note",
    "session_title",
    "garde cette seance lisible",
    "garde cette séance lisible",
    "le but est d'empiler",
    "rajouter du bruit",
    "reponds en json",
    "réponds en json",
    "genere ",
    "génère ",
)

_GENERIC_NUTRITION_MARKERS = (
    "rester simple",
    "reste simple",
    "pas besoin d'en faire trop",
    "rien a pousser",
    "rien à pousser",
    "soutenir la regularite",
    "soutenir la régularité",
)


@dataclass(frozen=True, slots=True)
class WorkoutContent:
    objective: str
    rationale: str
    execution: tuple[str, ...]
    coach_cue: str
    nutrition_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "rationale": self.rationale,
            "execution": list(self.execution),
            "coach_cue": self.coach_cue,
            "nutrition_note": self.nutrition_note,
        }


def build_workout_content(
    session: Any,
    *,
    watch_items: tuple[dict[str, Any], ...] | list[dict[str, Any]] | tuple[Any, ...] | list[Any] = (),
) -> WorkoutContent:
    template = select_session_template(
        sport_type=str(_value(session, "sport_type") or "running"),
        session_type=str(_value(session, "session_type") or "easy"),
    )
    if template.sport_type == "strength":
        strength = build_strength_workout(session=session, watch_items=watch_items)
        return WorkoutContent(
            objective=strength.objective,
            rationale=strength.rationale,
            execution=strength.execution,
            coach_cue=strength.coach_cue,
            nutrition_note=_normalize_nutrition(_clean_text(_value(session, "nutrition_focus"))),
        )
    objective = _clean_text(_value(session, "session_goal")) or template.goal
    rationale_source = _clean_text(_value(session, "session_note"))
    rationale = rationale_source if rationale_source and not _looks_system_like(rationale_source) else objective
    execution_source = _clean_text(_value(session, "session_description"))
    if not execution_source:
        execution_source = render_session_description(
            template,
            duration_min=_int(_value(session, "duration_min")),
        )
    execution = _split_execution(execution_source)
    coach_cue = template.watch_detail
    nutrition_note = _normalize_nutrition(_clean_text(_value(session, "nutrition_focus")))
    return WorkoutContent(
        objective=objective,
        rationale=rationale,
        execution=execution,
        coach_cue=coach_cue,
        nutrition_note=nutrition_note,
    )


def _split_execution(value: str) -> tuple[str, ...]:
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip().lstrip("-• ").strip()
        if line:
            lines.append(line)
    return tuple(lines)


def _normalize_nutrition(value: str) -> str:
    if not value:
        return ""
    lowered = value.lower()
    if _looks_system_like(value) or any(marker in lowered for marker in _GENERIC_NUTRITION_MARKERS):
        return "Hydrate-toi bien et reste sur quelque chose de simple aujourd'hui."
    return value


def _looks_system_like(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SYSTEM_MARKERS)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
