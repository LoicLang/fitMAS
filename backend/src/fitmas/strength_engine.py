from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fitmas.strength_exercise_bank import StrengthExercise, list_strength_exercises

_SHOULDER_MARKERS = ("epaule", "shoulder", "coiffe")
_KNEE_MARKERS = ("genou", "knee", "rotule")
_LOW_BACK_MARKERS = ("dos", "lomb", "back")
_LEG_FATIGUE_MARKERS = ("jambes", "mollet", "quad", "ischio", "leg fatigue", "jambe lourde")
_ACHILLES_MARKERS = ("achille", "achilles")
_FATIGUE_MARKERS = ("fatigue", "courbature", "crame", "epuise", "reprise", "relance", "restart")
_RUN_MARKERS = ("course", "run", "trail", "footing")
_SWIM_MARKERS = ("natation", "swim", "piscine")


@dataclass(frozen=True, slots=True)
class StrengthContext:
    goal: str
    symptom_flags: tuple[str, ...]
    fatigue_level: str
    duration_min: int
    equipment: tuple[str, ...]
    next_key_session_sport: str | None
    load_mode: str


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
) -> StrengthWorkout:
    context = derive_strength_context(session=session, watch_items=watch_items)
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
) -> StrengthContext:
    text_parts = [
        _clean_text(_value(session, "session_goal")),
        _clean_text(_value(session, "session_note")),
        _clean_text(_value(session, "session_description")),
        *[_clean_text(_value(item, "title")) for item in watch_items],
        *[_clean_text(_value(item, "detail")) for item in watch_items],
    ]
    combined = " ".join(part for part in text_parts if part).lower()
    session_type = str(_value(session, "session_type") or "general").lower()
    intensity = str(_value(session, "intensity") or "easy").lower()

    symptom_flags: list[str] = []
    if any(marker in combined for marker in _SHOULDER_MARKERS):
        symptom_flags.append("shoulder_pain")
    if any(marker in combined for marker in _KNEE_MARKERS):
        symptom_flags.append("knee_pain")
    if any(marker in combined for marker in _LOW_BACK_MARKERS):
        symptom_flags.append("low_back_risk")
    if any(marker in combined for marker in _LEG_FATIGUE_MARKERS):
        symptom_flags.append("leg_fatigue")
    if any(marker in combined for marker in _ACHILLES_MARKERS):
        symptom_flags.append("achilles_pain")

    next_key_session_sport = None
    if any(marker in combined for marker in _SWIM_MARKERS):
        next_key_session_sport = "swimming"
    elif any(marker in combined for marker in _RUN_MARKERS):
        next_key_session_sport = "running"

    fatigue_level = "high" if any(marker in combined for marker in _FATIGUE_MARKERS) or intensity == "easy" else "medium"
    if session_type == "mobility":
        goal = "mobility_restore"
    elif session_type == "core":
        goal = "core_support"
    elif next_key_session_sport == "swimming":
        goal = "support_swim"
    elif next_key_session_sport == "running":
        goal = "support_run"
    elif fatigue_level == "high":
        goal = "restart_consistency"
    else:
        goal = "general_support"

    return StrengthContext(
        goal=goal,
        symptom_flags=tuple(symptom_flags),
        fatigue_level=fatigue_level,
        duration_min=max(20, int(_value(session, "duration_min") or 30)),
        equipment=("bodyweight",),
        next_key_session_sport=next_key_session_sport,
        load_mode="easy" if intensity in {"easy", "recovery"} else "standard",
    )


def select_strength_blueprint(context: StrengthContext) -> StrengthBlueprint:
    flags = set(context.symptom_flags)
    if context.goal == "mobility_restore":
        return _BLUEPRINTS["mobility_restore"]
    if "shoulder_pain" in flags or context.goal == "support_swim":
        return _BLUEPRINTS["lower_stability_protect_shoulders"]
    if "leg_fatigue" in flags or context.goal == "support_run":
        return _BLUEPRINTS["upper_core_protect_legs"]
    if "low_back_risk" in flags or context.goal == "core_support":
        return _BLUEPRINTS["minimum_effective_dose"]
    if context.goal == "restart_consistency" or context.fatigue_level == "high":
        return _BLUEPRINTS["restart_consistency_strength"]
    return _BLUEPRINTS["full_body_support"]


def render_strength_execution(*, blueprint: StrengthBlueprint, context: StrengthContext) -> tuple[str, ...]:
    exercises = list_strength_exercises()
    used_keys: set[str] = set()
    lines: list[str] = []
    for slot in blueprint.slots:
        exercise = _pick_exercise(exercises=exercises, slot=slot, context=context, used_keys=used_keys)
        if exercise is None:
            continue
        used_keys.add(exercise.key)
        prescription = exercise.prescription_light if context.load_mode == "easy" or context.fatigue_level == "high" else exercise.prescription_standard
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


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
