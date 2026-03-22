from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.planning_config import get_global_planning_config

PAIN_KEYWORDS = (
    "douleur",
    "pain",
    "blessure",
    "injury",
    "tendon",
    "genou",
    "knee",
    "cheville",
    "ankle",
    "mollet",
    "achille",
)
FATIGUE_KEYWORDS = (
    "fatigue",
    "lourd",
    "lourde",
    "crame",
    "cramé",
    "epuise",
    "épuisé",
    "courbature",
    "maladie",
    "malade",
)
SLEEP_KEYWORDS = ("sommeil", "sleep", "insomnie", "mal dormi", "nuit courte")
MENTAL_LOAD_KEYWORDS = ("stress", "pression", "culpabilite", "culpabilité", "demotive", "démotivé")
TRAVEL_KEYWORDS = ("deplacement", "déplacement", "travel", "voyage", "famille", "boulot", "travail")


@dataclass(frozen=True, slots=True)
class ReadinessState:
    user_id: int
    date: date
    physical: str
    mental: str
    logistical: str
    injury_risk: str
    risk_flags: tuple[str, ...]
    summary: str


def build_readiness_state(
    *,
    profile: AthleteProfileSnapshot,
    fitness: FitnessSnapshot,
    facts: Sequence[Any] | None = None,
) -> ReadinessState:
    active_texts = _collect_active_texts(profile, facts or [])
    risk_flags = _derive_risk_flags(profile=profile, fitness=fitness, texts=active_texts)
    physical = _physical_state(fitness=fitness, risk_flags=risk_flags)
    mental = _mental_state(fitness=fitness, texts=active_texts)
    logistical = _logistical_state(profile=profile, texts=active_texts)
    injury_risk = _injury_risk(risk_flags)
    summary = _build_summary(
        physical=physical,
        mental=mental,
        logistical=logistical,
        injury_risk=injury_risk,
        risk_flags=risk_flags,
    )
    return ReadinessState(
        user_id=profile.user_id,
        date=fitness.date,
        physical=physical,
        mental=mental,
        logistical=logistical,
        injury_risk=injury_risk,
        risk_flags=tuple(risk_flags),
        summary=summary,
    )


def _derive_risk_flags(
    *,
    profile: AthleteProfileSnapshot,
    fitness: FitnessSnapshot,
    texts: Sequence[str],
) -> list[str]:
    config = get_global_planning_config()
    flags: list[str] = []
    combined = " ".join(texts).lower()

    if any(keyword in combined for keyword in PAIN_KEYWORDS):
        flags.append("pain_reported")
    if any(keyword in combined for keyword in FATIGUE_KEYWORDS):
        flags.append("fatigue_reported")
    if any(keyword in combined for keyword in SLEEP_KEYWORDS):
        flags.append("sleep_risk")
    if any(keyword in combined for keyword in TRAVEL_KEYWORDS):
        flags.append("travel_constraint")
    if fitness.tsb <= -10:
        flags.append("high_fatigue_load")
    if fitness.ramp_rate > config.max_weekly_ramp_rate:
        flags.append("ramp_rate_high")
    if fitness.completion_rate_14d and fitness.completion_rate_14d < 0.5:
        flags.append("low_recent_completion")
    if not profile.weekly_availability:
        flags.append("low_schedule_clarity")
    return flags


def _physical_state(*, fitness: FitnessSnapshot, risk_flags: Sequence[str]) -> str:
    if "pain_reported" in risk_flags:
        return "low"
    if "high_fatigue_load" in risk_flags or "ramp_rate_high" in risk_flags:
        return "low"
    if fitness.tsb >= 5 and fitness.ramp_rate <= 0.08:
        return "high"
    return "medium"


def _mental_state(*, fitness: FitnessSnapshot, texts: Sequence[str]) -> str:
    combined = " ".join(texts).lower()
    if any(keyword in combined for keyword in MENTAL_LOAD_KEYWORDS):
        return "low"
    if fitness.completion_rate_14d >= 0.75:
        return "high"
    if fitness.completion_rate_14d < 0.4:
        return "low"
    return "medium"


def _logistical_state(*, profile: AthleteProfileSnapshot, texts: Sequence[str]) -> str:
    combined = " ".join(texts).lower()
    if any(keyword in combined for keyword in TRAVEL_KEYWORDS):
        return "constrained"
    if not profile.weekly_availability:
        return "blocked"
    return "clear"


def _injury_risk(risk_flags: Sequence[str]) -> str:
    if "pain_reported" in risk_flags:
        return "high"
    if "fatigue_reported" in risk_flags or "sleep_risk" in risk_flags:
        return "medium"
    return "low"


def _build_summary(
    *,
    physical: str,
    mental: str,
    logistical: str,
    injury_risk: str,
    risk_flags: Sequence[str],
) -> str:
    summary = (
        f"Physique {physical}, mental {mental}, logistique {logistical}, risque blessure {injury_risk}."
    )
    if risk_flags:
        summary += f" Flags: {', '.join(risk_flags[:4])}."
    return summary


def _collect_active_texts(profile: AthleteProfileSnapshot, facts: Sequence[Any]) -> list[str]:
    texts = [
        *profile.constraints,
        *profile.preferences,
        *profile.goals,
        profile.athlete_identity_summary,
        profile.coach_style_notes,
    ]
    for fact in facts:
        if getattr(fact, "active", True) is False:
            continue
        value = _value(fact, "value")
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return texts


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
