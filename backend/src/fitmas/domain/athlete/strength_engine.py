from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fitmas.domain.athlete.strength_exercise_bank import StrengthExercise, list_strength_exercises
from fitmas.domain.athlete.strength_signals import StrengthSignals, derive_strength_signals


@dataclass(frozen=True, slots=True)
class StrengthContext:
    goal: str
    symptom_flags: tuple[str, ...]
    fatigue_level: str
    duration_min: int
    equipment: tuple[str, ...]
    protected_sport: str | None
    load_mode: str
    recent_completion_band: str
    recent_load_band: str
    fatigue_flag: bool
    available_time_band: str


@dataclass(frozen=True, slots=True)
class StrengthSlot:
    required_tags: tuple[str, ...]
    fallback_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrengthBlueprint:
    key: str
    objective: str
    rationale: str
    coach_cue: str
    slots: tuple[StrengthSlot, ...]


@dataclass(frozen=True, slots=True)
class StrengthWorkout:
    objective: str
    rationale: str
    execution: tuple[str, ...]
    coach_cue: str
    blueprint_key: str


_BLUEPRINTS: dict[str, StrengthBlueprint] = {
    "full_body_support": StrengthBlueprint(
        key="full_body_support",
        objective="Remettre du tonus global sans alourdir la semaine.",
        rationale="Bloc complet, simple et propre pour soutenir la regularite.",
        coach_cue="Laisse 2-3 reps en reserve et privilegie l'execution.",
        slots=(
            StrengthSlot(("warmup", "mobility", "lower")),
            StrengthSlot(("warmup", "mobility", "upper"), ("warmup", "mobility", "scapular")),
            StrengthSlot(("main", "lower", "squat"), ("main", "lower", "hinge")),
            StrengthSlot(("main", "upper", "push"), ("main", "upper", "scapular")),
            StrengthSlot(("main", "lower", "hinge"), ("main", "lower", "calves")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
            StrengthSlot(("core", "anti_lateral"), ("core", "anti_rotation")),
        ),
    ),
    "upper_core_protect_legs": StrengthBlueprint(
        key="upper_core_protect_legs",
        objective="Soutenir le haut du corps et le tronc sans charger les jambes.",
        rationale="On protege les jambes avant ou apres un bloc course en gardant seulement du support utile.",
        coach_cue="Reste leger sur les jambes. Le vrai sujet est le controle.",
        slots=(
            StrengthSlot(("warmup", "mobility", "upper"), ("warmup", "mobility", "scapular")),
            StrengthSlot(("main", "upper", "scapular")),
            StrengthSlot(("main", "upper", "push"), ("main", "upper", "pull")),
            StrengthSlot(("main", "lower", "hinge")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
            StrengthSlot(("core", "anti_rotation"), ("core", "anti_extension")),
        ),
    ),
    "lower_stability_protect_shoulders": StrengthBlueprint(
        key="lower_stability_protect_shoulders",
        objective="Garder du bas du corps et du tronc sans irriter le haut du corps.",
        rationale="On laisse de la marge aux epaules tout en gardant de la stabilite utile.",
        coach_cue="Aucun mouvement douloureux en haut du corps. Tout doit rester facile a propre.",
        slots=(
            StrengthSlot(("warmup", "mobility", "lower")),
            StrengthSlot(("main", "lower", "hinge")),
            StrengthSlot(("main", "lower", "squat"), ("main", "lower", "calves")),
            StrengthSlot(("main", "lower", "single_leg"), ("main", "lower", "calves")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
            StrengthSlot(("core", "anti_rotation"), ("core", "anti_extension")),
        ),
    ),
    "mobility_restore": StrengthBlueprint(
        key="mobility_restore",
        objective="Rendre le corps plus disponible sans chercher de fatigue.",
        rationale="Jour de mobilite ou de protection. On remet de l'amplitude et du controle.",
        coach_cue="Respire, bouge propre, arrete avant toute crispation.",
        slots=(
            StrengthSlot(("warmup", "mobility", "lower")),
            StrengthSlot(("warmup", "mobility", "upper"), ("warmup", "mobility", "scapular")),
            StrengthSlot(("core", "anti_rotation"), ("core", "anti_extension")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
        ),
    ),
    "minimum_effective_dose": StrengthBlueprint(
        key="minimum_effective_dose",
        objective="Garder le minimum utile sans ouvrir une vraie dette de fatigue.",
        rationale="Dose courte, stable, pour ne pas sortir du rythme.",
        coach_cue="Court, propre, stop avant de tirer sur le systeme.",
        slots=(
            StrengthSlot(("warmup", "mobility", "lower")),
            StrengthSlot(("main", "lower", "hinge")),
            StrengthSlot(("main", "upper", "scapular"), ("main", "upper", "push")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
            StrengthSlot(("core", "anti_rotation"), ("core", "anti_extension")),
        ),
    ),
    "restart_consistency_strength": StrengthBlueprint(
        key="restart_consistency_strength",
        objective="Reprendre un renfo simple et tenable.",
        rationale="On relance la regularite avec une dose minimale mais actionnable.",
        coach_cue="Tu dois finir avec la sensation d'en avoir encore sous le pied.",
        slots=(
            StrengthSlot(("warmup", "mobility", "lower")),
            StrengthSlot(("warmup", "mobility", "upper"), ("warmup", "mobility", "scapular")),
            StrengthSlot(("main", "lower", "hinge")),
            StrengthSlot(("main", "upper", "scapular"), ("main", "upper", "push")),
            StrengthSlot(("core", "anti_extension"), ("core", "anti_rotation")),
        ),
    ),
}


def build_strength_workout(
    *,
    session: Any,
    watch_items: Sequence[dict[str, Any]] | Sequence[Any] = (),
    signals: StrengthSignals | dict[str, Any] | None = None,
) -> StrengthWorkout:
    context = derive_strength_context(session=session, watch_items=watch_items, signals=signals)
    blueprint = select_strength_blueprint(context)
    execution = render_strength_execution(blueprint=blueprint, context=context)
    objective = _clean_text(_value(session, "session_goal")) or blueprint.objective
    rationale = _clean_text(_value(session, "session_note")) or blueprint.rationale
    return StrengthWorkout(
        objective=objective,
        rationale=rationale,
        execution=execution,
        coach_cue=blueprint.coach_cue,
        blueprint_key=blueprint.key,
    )


def derive_strength_context(
    *,
    session: Any,
    watch_items: Sequence[dict[str, Any]] | Sequence[Any] = (),
    signals: StrengthSignals | dict[str, Any] | None = None,
) -> StrengthContext:
    resolved_signals = _coerce_signals(signals) or derive_strength_signals(session=session, watch_items=watch_items)
    session_type = str(_value(session, "session_type") or "general").lower()
    intensity = str(_value(session, "intensity") or "easy").lower()
    if session_type == "mobility":
        goal = "mobility_restore"
    elif session_type == "core":
        goal = "core_support"
    elif resolved_signals.protected_sport == "swimming":
        goal = "support_swim"
    elif resolved_signals.protected_sport == "running":
        goal = "support_run"
    elif resolved_signals.recent_completion_band == "low" or resolved_signals.fatigue_flag:
        goal = "restart_consistency"
    else:
        goal = "general_support"

    return StrengthContext(
        goal=goal,
        symptom_flags=resolved_signals.health_flags,
        fatigue_level="high" if resolved_signals.fatigue_flag else "medium",
        duration_min=max(20, int(_value(session, "duration_min") or 30)),
        equipment=("bodyweight",),
        protected_sport=resolved_signals.protected_sport,
        load_mode=_select_load_mode(signals=resolved_signals, intensity=intensity),
        recent_completion_band=resolved_signals.recent_completion_band,
        recent_load_band=resolved_signals.recent_load_band,
        fatigue_flag=resolved_signals.fatigue_flag,
        available_time_band=resolved_signals.available_time_band,
    )


def select_strength_blueprint(context: StrengthContext) -> StrengthBlueprint:
    flags = set(context.symptom_flags)
    if context.goal == "mobility_restore":
        return _BLUEPRINTS["mobility_restore"]
    if "shoulder_pain" in flags or context.protected_sport == "swimming":
        return _BLUEPRINTS["lower_stability_protect_shoulders"]
    if flags.intersection({"leg_fatigue", "knee_pain", "achilles_pain"}) or context.protected_sport == "running":
        return _BLUEPRINTS["upper_core_protect_legs"]
    if "low_back_risk" in flags or context.goal == "core_support":
        return _BLUEPRINTS["minimum_effective_dose"]
    if context.load_mode == "minimum_effective_dose":
        return _BLUEPRINTS["minimum_effective_dose"]
    if context.goal == "restart_consistency" or context.recent_completion_band == "low":
        return _BLUEPRINTS["restart_consistency_strength"]
    return _BLUEPRINTS["full_body_support"]


def render_strength_execution(*, blueprint: StrengthBlueprint, context: StrengthContext) -> tuple[str, ...]:
    exercises = list_strength_exercises()
    used_keys: set[str] = set()
    lines: list[str] = []
    for slot in blueprint.slots[:_slot_budget(blueprint=blueprint, context=context)]:
        exercise = _pick_exercise(exercises=exercises, slot=slot, context=context, used_keys=used_keys)
        if exercise is None:
            continue
        used_keys.add(exercise.key)
        prescription = exercise.prescription_standard if context.load_mode == "full" else exercise.prescription_light
        lines.append(f"{exercise.name} — {prescription} — recup {exercise.rest_seconds}s")
    return tuple(lines)


def _pick_exercise(
    *,
    exercises: Sequence[StrengthExercise],
    slot: StrengthSlot,
    context: StrengthContext,
    used_keys: set[str],
) -> StrengthExercise | None:
    for tags in (slot.required_tags, slot.fallback_tags):
        if not tags:
            continue
        candidate = next(
            (
                exercise
                for exercise in exercises
                if exercise.key not in used_keys
                and _matches(exercise=exercise, required_tags=tags, context=context)
            ),
            None,
        )
        if candidate is not None:
            return candidate
    return None


def _matches(*, exercise: StrengthExercise, required_tags: tuple[str, ...], context: StrengthContext) -> bool:
    if any(flag in exercise.contraindications for flag in context.symptom_flags):
        return False
    return all(tag in exercise.tags for tag in required_tags)


def _select_load_mode(*, signals: StrengthSignals, intensity: str) -> str:
    easy_request = intensity in {"easy", "recovery", "mobility"}
    if signals.available_time_band == "short":
        return "minimum_effective_dose"
    if signals.recent_completion_band == "low" and (signals.fatigue_flag or signals.recent_load_band == "low"):
        return "minimum_effective_dose"
    if signals.fatigue_flag or signals.recent_completion_band == "low" or signals.recent_load_band == "low" or easy_request:
        return "light"
    return "full"


def _slot_budget(*, blueprint: StrengthBlueprint, context: StrengthContext) -> int:
    count = len(blueprint.slots)
    if context.load_mode == "full":
        return count
    if context.load_mode == "minimum_effective_dose":
        return min(count, 4 if context.available_time_band == "short" else 5)
    return min(count, 5 if context.available_time_band == "short" else max(count - 1, 4))


def _coerce_signals(value: StrengthSignals | dict[str, Any] | None) -> StrengthSignals | None:
    if value is None or isinstance(value, StrengthSignals):
        return value
    return StrengthSignals(
        recent_completion_band=str(value.get("recent_completion_band") or "ok"),
        recent_load_band=str(value.get("recent_load_band") or "ok"),
        fatigue_flag=bool(value.get("fatigue_flag")),
        health_flags=tuple(str(flag) for flag in value.get("health_flags") or ()),
        available_time_band=str(value.get("available_time_band") or "normal"),
        protected_sport=str(value.get("protected_sport")) if value.get("protected_sport") else None,
    )


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
