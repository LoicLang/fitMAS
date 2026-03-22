from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.planning_config import (
    get_level_planning_config,
    get_sport_planning_config,
)
from fitmas.readiness import ReadinessState

DECISION_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    user_id: int
    week_start: date
    decision_version: str
    planning_mode: str
    adaptation_level: str
    adaptation_scope: str
    weekly_target_tss: float
    intensity_distribution: str
    key_session_count: int
    strength_session_count: int
    long_session: bool
    rationale: tuple[str, ...]
    adaptations: tuple[str, ...]
    risk_flags: tuple[str, ...]


def build_planning_decision(
    *,
    profile: AthleteProfileSnapshot,
    fitness: FitnessSnapshot,
    readiness: ReadinessState,
    mesocycle_week: int = 1,
    week_start: date | None = None,
) -> PlanningDecision:
    resolved_week_start = week_start or (fitness.date - timedelta(days=fitness.date.weekday()))
    primary_sport = profile.primary_sport or "running"
    sport_config = get_sport_planning_config(primary_sport)
    level = profile.level_by_sport.get(primary_sport, "unknown")
    level_config = get_level_planning_config(level)
    baseline_tss = _baseline_tss(fitness=fitness, level_floor=level_config.weekly_tss_floor)

    planning_mode, adaptation_level, adaptation_scope = _pick_mode(
        readiness=readiness,
        mesocycle_week=mesocycle_week,
    )
    weekly_target_tss = _target_tss(
        planning_mode=planning_mode,
        baseline_tss=baseline_tss,
        level_floor=level_config.weekly_tss_floor,
        level_ceiling=level_config.weekly_tss_ceiling,
    )
    key_session_count = _key_session_count(planning_mode=planning_mode, default_key_sessions=sport_config.key_sessions_default)
    strength_session_count = _strength_session_count(profile=profile, readiness=readiness, planning_mode=planning_mode)
    long_session = sport_config.supports_long_session and planning_mode not in {"injury_protection", "deload"}
    intensity_distribution = _intensity_distribution(planning_mode)
    rationale = tuple(
        _dedupe(
            [
                *_base_rationale(planning_mode),
                *[flag.replace("_", " ") for flag in readiness.risk_flags[:4]],
            ]
        )
    )
    adaptations = tuple(
        _dedupe(
            [
                *_base_adaptations(planning_mode, primary_sport=primary_sport),
                *(_risk_adaptations(readiness.risk_flags)),
            ]
        )
    )
    return PlanningDecision(
        user_id=profile.user_id,
        week_start=resolved_week_start,
        decision_version=DECISION_VERSION,
        planning_mode=planning_mode,
        adaptation_level=adaptation_level,
        adaptation_scope=adaptation_scope,
        weekly_target_tss=weekly_target_tss,
        intensity_distribution=intensity_distribution,
        key_session_count=key_session_count,
        strength_session_count=strength_session_count,
        long_session=long_session,
        rationale=rationale,
        adaptations=adaptations,
        risk_flags=readiness.risk_flags,
    )


def _pick_mode(*, readiness: ReadinessState, mesocycle_week: int) -> tuple[str, str, str]:
    flags = set(readiness.risk_flags)
    if readiness.injury_risk == "high" or "pain_reported" in flags:
        return "injury_protection", "high", "week"
    if mesocycle_week > 0 and mesocycle_week % 4 == 0:
        return "deload", "medium", "week"
    if "high_fatigue_load" in flags or "ramp_rate_high" in flags or readiness.physical == "low":
        return "reduce_load", "medium", "week"
    if readiness.logistical == "blocked" or "travel_constraint" in flags or "low_recent_completion" in flags:
        return "tactical_adjustment", "low", "microcycle"
    if readiness.physical == "high" and readiness.mental == "high" and readiness.logistical == "clear":
        return "increase_load", "low", "week"
    return "maintain_load", "none", "week"


def _baseline_tss(*, fitness: FitnessSnapshot, level_floor: float) -> float:
    candidates = [fitness.weekly_target_tss, fitness.weekly_actual_tss, level_floor]
    return max(candidate for candidate in candidates if candidate is not None)


def _target_tss(
    *,
    planning_mode: str,
    baseline_tss: float,
    level_floor: float,
    level_ceiling: float,
) -> float:
    multipliers = {
        "increase_load": 1.05,
        "maintain_load": 1.0,
        "reduce_load": 0.85,
        "deload": 0.65,
        "tactical_adjustment": 0.95,
        "injury_protection": 0.55,
    }
    raw_target = baseline_tss * multipliers[planning_mode]
    if planning_mode == "injury_protection":
        return round(min(raw_target, level_floor), 1)
    return round(min(level_ceiling, max(level_floor, raw_target)), 1)


def _key_session_count(*, planning_mode: str, default_key_sessions: int) -> int:
    if planning_mode == "injury_protection":
        return 0
    if planning_mode in {"deload", "reduce_load"}:
        return max(1, default_key_sessions - 1)
    if planning_mode == "increase_load":
        return min(default_key_sessions + 1, 3)
    return default_key_sessions


def _strength_session_count(
    *,
    profile: AthleteProfileSnapshot,
    readiness: ReadinessState,
    planning_mode: str,
) -> int:
    if planning_mode == "injury_protection":
        return 0
    if profile.primary_sport == "strength":
        return 2 if readiness.logistical == "clear" else 1
    return 1 if readiness.logistical != "blocked" else 0


def _intensity_distribution(planning_mode: str) -> str:
    mapping = {
        "increase_load": "build",
        "maintain_load": "balanced",
        "reduce_load": "lighter",
        "deload": "recovery",
        "tactical_adjustment": "conservative",
        "injury_protection": "protective",
    }
    return mapping[planning_mode]


def _base_rationale(planning_mode: str) -> list[str]:
    mapping = {
        "increase_load": ["readiness haute", "fenetre de progression exploitable"],
        "maintain_load": ["stabilite suffisante", "pas de signal fort pour changer la charge"],
        "reduce_load": ["fatigue a contenir", "charge recente a calmer"],
        "deload": ["semaine 4 de cycle", "recovery planifiee"],
        "tactical_adjustment": ["contraintes recentes a absorber", "structure globale preservee"],
        "injury_protection": ["protection prioritaire", "charge agressive exclue"],
    }
    return mapping[planning_mode]


def _base_adaptations(planning_mode: str, *, primary_sport: str) -> list[str]:
    mapping = {
        "increase_load": [
            f"garder un bloc cle en {primary_sport}",
            "ajouter un peu de charge sans casser la regularite",
        ],
        "maintain_load": [
            "conserver la structure utile",
            "stabiliser la charge hebdo",
        ],
        "reduce_load": [
            "alleger la densite de la semaine",
            "garder seulement les stimuli qui comptent",
        ],
        "deload": [
            "rester mobile sans chercher a performer",
            "baisser le stress global",
        ],
        "tactical_adjustment": [
            "adapter les jours plus que le fond",
            "laisser de la marge logistique",
        ],
        "injury_protection": [
            "retirer les intensites inutiles",
            "privilegier recuperation et maintien minimum",
        ],
    }
    return mapping[planning_mode]


def _risk_adaptations(risk_flags: tuple[str, ...]) -> list[str]:
    mapping = {
        "pain_reported": "eviter les seances dures sur la zone sensible",
        "fatigue_reported": "reduire l'accumulation de fatigue",
        "sleep_risk": "laisser plus de marge autour des seances cles",
        "travel_constraint": "prioriser des seances deplacables",
        "high_fatigue_load": "ralentir la progression cette semaine",
        "ramp_rate_high": "stopper la hausse de charge brutale",
        "low_recent_completion": "revenir a une semaine plus tenable",
        "low_schedule_clarity": "eviter un plan trop rigide",
    }
    return [mapping[flag] for flag in risk_flags if flag in mapping]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique
