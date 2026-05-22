from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrengthExercise:
    key: str
    name: str
    tags: tuple[str, ...]
    contraindications: tuple[str, ...]
    prescription_light: str
    prescription_standard: str
    rest_seconds: int
    cue: str


_EXERCISES: tuple[StrengthExercise, ...] = (
    StrengthExercise(
        key="breathing_brace",
        name="Respiration + gainage souffle",
        tags=("warmup", "mobility", "core"),
        contraindications=(),
        prescription_light="2 x 5 respirations lentes",
        prescription_standard="2 x 5 respirations lentes",
        rest_seconds=20,
        cue="Ribs basses, souffle long.",
    ),
    StrengthExercise(
        key="hip_opener",
        name="Ouverture hanches 90/90",
        tags=("warmup", "mobility", "lower"),
        contraindications=(),
        prescription_light="2 x 30s par cote",
        prescription_standard="2 x 40s par cote",
        rest_seconds=20,
        cue="Cherche de l'amplitude, pas la douleur.",
    ),
    StrengthExercise(
        key="thoracic_rotation",
        name="Rotation thoracique au sol",
        tags=("warmup", "mobility", "upper", "scapular"),
        contraindications=(),
        prescription_light="2 x 6 reps par cote",
        prescription_standard="2 x 8 reps par cote",
        rest_seconds=20,
        cue="Garde le bassin stable.",
    ),
    StrengthExercise(
        key="squat_box",
        name="Squat controle au poids du corps",
        tags=("main", "lower", "squat"),
        contraindications=("knee_pain", "leg_fatigue"),
        prescription_light="2 x 8 reps",
        prescription_standard="3 x 10 reps",
        rest_seconds=45,
        cue="Descends propre, remonte fluide.",
    ),
    StrengthExercise(
        key="split_squat_short",
        name="Fente courte controlee",
        tags=("main", "lower", "single_leg"),
        contraindications=("knee_pain", "leg_fatigue"),
        prescription_light="2 x 6 reps par jambe",
        prescription_standard="3 x 8 reps par jambe",
        rest_seconds=45,
        cue="Petit amplitude, bassin stable.",
    ),
    StrengthExercise(
        key="glute_bridge",
        name="Pont fessier",
        tags=("main", "lower", "hinge"),
        contraindications=(),
        prescription_light="2 x 10 reps",
        prescription_standard="3 x 12 reps",
        rest_seconds=40,
        cue="Pousse avec les talons, haut du dos pose.",
    ),
    StrengthExercise(
        key="calf_raise",
        name="Mollets debout controles",
        tags=("main", "lower", "calves"),
        contraindications=("achilles_pain",),
        prescription_light="2 x 10 reps",
        prescription_standard="3 x 12 reps",
        rest_seconds=35,
        cue="Monte net, redescends lentement.",
    ),
    StrengthExercise(
        key="incline_pushup",
        name="Pompes inclinees",
        tags=("main", "upper", "push"),
        contraindications=("shoulder_pain",),
        prescription_light="2 x 6 reps",
        prescription_standard="3 x 8 reps",
        rest_seconds=45,
        cue="Gainage fort, epaules basses.",
    ),
    StrengthExercise(
        key="wall_slide",
        name="Wall slides scapulaires",
        tags=("main", "upper", "scapular"),
        contraindications=(),
        prescription_light="2 x 8 reps",
        prescription_standard="3 x 10 reps",
        rest_seconds=35,
        cue="Monte sans hausser les epaules.",
    ),
    StrengthExercise(
        key="prone_swimmer",
        name="Nageur prone controle",
        tags=("main", "upper", "scapular", "pull"),
        contraindications=("low_back_risk",),
        prescription_light="2 x 6 reps",
        prescription_standard="3 x 8 reps",
        rest_seconds=35,
        cue="Petit amplitude, nuque longue.",
    ),
    StrengthExercise(
        key="dead_bug",
        name="Dead bug",
        tags=("core", "anti_extension"),
        contraindications=(),
        prescription_light="2 x 6 reps par cote",
        prescription_standard="3 x 8 reps par cote",
        rest_seconds=30,
        cue="Bas du dos plaque, souffle long.",
    ),
    StrengthExercise(
        key="bird_dog",
        name="Bird dog",
        tags=("core", "anti_rotation"),
        contraindications=(),
        prescription_light="2 x 6 reps par cote",
        prescription_standard="3 x 8 reps par cote",
        rest_seconds=30,
        cue="Hanches fixes, mouvement lent.",
    ),
    StrengthExercise(
        key="side_plank",
        name="Gainage lateral",
        tags=("core", "anti_lateral"),
        contraindications=("shoulder_pain",),
        prescription_light="2 x 20s par cote",
        prescription_standard="3 x 30s par cote",
        rest_seconds=30,
        cue="Aligne tete, bassin, chevilles.",
    ),
)

_INDEX = {exercise.key: exercise for exercise in _EXERCISES}


def list_strength_exercises() -> tuple[StrengthExercise, ...]:
    return _EXERCISES


def get_strength_exercise(key: str) -> StrengthExercise | None:
    return _INDEX.get(key)
