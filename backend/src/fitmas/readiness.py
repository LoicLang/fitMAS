from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.domain.memory.fact_memory import select_readiness_facts
from fitmas.fitness_snapshot import FitnessSnapshot
from fitmas.planning_config import get_global_planning_config
from fitmas.domain.execution.recent_reality import RecentRealityWindow


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
    recent_reality: RecentRealityWindow | None = None,
) -> ReadinessState:
    readiness_facts = select_readiness_facts(facts or [])
    risk_flags = _derive_risk_flags(
        fitness=fitness,
        readiness_facts=readiness_facts,
        recent_reality=recent_reality,
    )
    physical = _physical_state(fitness=fitness, risk_flags=risk_flags)
    mental = _mental_state(fitness=fitness, risk_flags=risk_flags)
    logistical = _logistical_state(profile=profile, risk_flags=risk_flags)
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
    fitness: FitnessSnapshot,
    readiness_facts: Sequence[Any],
    recent_reality: RecentRealityWindow | None = None,
) -> list[str]:
    config = get_global_planning_config()
    flags: list[str] = []
    for flag in _structured_readiness_flags(readiness_facts):
        if flag not in flags:
            flags.append(flag)
    if fitness.tsb <= -10:
        flags.append("high_fatigue_load")
    if fitness.ramp_rate > config.max_weekly_ramp_rate:
        flags.append("ramp_rate_high")
    if recent_reality is not None:
        if recent_reality.planned_sessions_7d >= 3 and recent_reality.compliance_confirmed < 0.6:
            flags.append("low_recent_completion")
        if recent_reality.planned_tss_7d >= 80 and recent_reality.load_ratio < 0.7:
            flags.append("load_under_target")
        if recent_reality.missed_streak_days >= 2:
            flags.append("consistency_streak_broken")
    elif fitness.completion_rate_14d and fitness.completion_rate_14d < 0.5:
        flags.append("low_recent_completion")
    return flags


def _physical_state(*, fitness: FitnessSnapshot, risk_flags: Sequence[str]) -> str:
    if "pain_reported" in risk_flags:
        return "low"
    if "high_fatigue_load" in risk_flags or "ramp_rate_high" in risk_flags:
        return "low"
    if fitness.tsb >= 5 and fitness.ramp_rate <= 0.08:
        return "high"
    return "medium"


def _mental_state(*, fitness: FitnessSnapshot, risk_flags: Sequence[str]) -> str:
    if "sleep_risk" in risk_flags:
        return "low"
    if fitness.completion_rate_14d >= 0.75:
        return "high"
    if fitness.completion_rate_14d < 0.4:
        return "low"
    return "medium"


def _logistical_state(*, profile: AthleteProfileSnapshot, risk_flags: Sequence[str]) -> str:
    if "travel_constraint" in risk_flags:
        return "constrained"
    return "clear"


def _injury_risk(risk_flags: Sequence[str]) -> str:
    if "pain_reported" in risk_flags:
        return "high"
    if "health_watch" in risk_flags or "fatigue_reported" in risk_flags or "sleep_risk" in risk_flags:
        return "medium"
    return "low"


def _structured_readiness_flags(facts: Sequence[Any]) -> list[str]:
    flags: list[str] = []
    for fact in facts:
        category = str(_value(fact, "category") or "").strip().lower()
        signal_kind = str(_value(fact, "signal_kind") or "").strip().lower()
        severity = str(_value(fact, "severity") or _value(fact, "urgency") or "medium").strip().lower()
        status = str(_value(fact, "status") or "open").strip().lower()

        if category == "health":
            if signal_kind in {"pain", "injury"}:
                flags.append("pain_reported" if _is_significant(severity, status) else "health_watch")
            elif signal_kind == "tension":
                flags.append("pain_reported" if _is_high(severity, status) else "health_watch")
            elif signal_kind in {"fatigue", "illness"}:
                flags.append("fatigue_reported")
            elif signal_kind == "sleep":
                flags.append("sleep_risk")
            elif _is_high(severity, status):
                flags.append("health_watch")
        elif category == "fatigue":
            if _is_significant(severity, status):
                flags.append("fatigue_reported")
        elif category in {"availability", "schedule"}:
            if signal_kind in {"availability_limited", "availability_unavailable"} or _is_significant(severity, status):
                flags.append("travel_constraint")
    return flags


def _is_significant(severity: str, status: str) -> bool:
    return severity in {"moderate", "medium", "severe", "high"} or status in {"new", "ongoing", "worsening"}


def _is_high(severity: str, status: str) -> bool:
    return severity in {"severe", "high"} or status == "worsening"


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


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
