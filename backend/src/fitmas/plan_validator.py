from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fitmas.fitness_snapshot import estimate_scheduled_session_tss
from fitmas.intensity_distribution import check_distribution
from fitmas.planning_config import get_global_planning_config, get_sport_planning_config

REST_SPORTS = {"rest", "off"}
HARD_INTENSITIES = {"hard"}
KEY_PRIORITIES = {"seance cle", "repere fort", "high", "key", "important"}
DAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    detail: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    issues: tuple[ValidationIssue, ...]


def validate_week_plan(
    days: Sequence[dict[str, Any]],
    *,
    primary_sport: str,
    planning_decision: Any | None = None,
) -> ValidationResult:
    config = get_global_planning_config()
    issues: list[ValidationIssue] = []
    ordered_days = [day for day in days if isinstance(day, dict)]

    if len(ordered_days) != 7:
        issues.append(ValidationIssue("day_count", f"7 jours attendus, recu {len(ordered_days)}."))
        return ValidationResult(is_valid=False, issues=tuple(issues))

    seen_days = [str(day.get("day") or "") for day in ordered_days]
    if tuple(seen_days) != DAY_ORDER:
        issues.append(ValidationIssue("day_order", "Le plan doit rester aligne de lundi a dimanche."))

    recovery_days = 0
    key_sessions = 0
    primary_sport_sessions = 0
    hard_indexes: list[int] = []
    estimated_week_tss = 0.0

    for index, day in enumerate(ordered_days):
        sport_type = str(day.get("sport_type") or "").lower()
        if sport_type == primary_sport:
            primary_sport_sessions += 1
        if sport_type in REST_SPORTS:
            recovery_days += 1
            continue

        duration_min = int(day.get("duration_min") or 0)
        sport_config = get_sport_planning_config(sport_type)
        if duration_min < sport_config.min_session_duration_min:
            issues.append(
                ValidationIssue(
                    "duration_too_short",
                    f"{day.get('day')}: duree {duration_min} trop courte pour {sport_type}.",
                )
            )
        if duration_min > sport_config.max_session_duration_min:
            issues.append(
                ValidationIssue(
                    "duration_too_long",
                    f"{day.get('day')}: duree {duration_min} trop longue pour {sport_type}.",
                )
            )

        if _is_key_session(day):
            key_sessions += 1
        if _is_hard_session(day):
            hard_indexes.append(index)
        estimated_week_tss += estimate_scheduled_session_tss(day)

    allowed_key_sessions = config.max_key_sessions_per_week
    if planning_decision is not None:
        allowed_key_sessions = max(allowed_key_sessions, int(getattr(planning_decision, "key_session_count", allowed_key_sessions) or 0))
        if getattr(planning_decision, "planning_mode", "") == "injury_protection" and hard_indexes:
            issues.append(ValidationIssue("injury_protection_hard_session", "Le mode injury_protection ne doit pas garder de seance dure."))
        target_tss = float(getattr(planning_decision, "weekly_target_tss", 0.0) or 0.0)
        if target_tss > 0:
            tolerance = max(35.0, target_tss * 0.35)
            if abs(estimated_week_tss - target_tss) > tolerance:
                issues.append(
                    ValidationIssue(
                        "target_tss_mismatch",
                        f"TSS estime {round(estimated_week_tss, 1)} trop loin de la cible {round(target_tss, 1)}.",
                        severity="warning",
                    )
                )

    if recovery_days < config.min_recovery_days_per_week:
        issues.append(ValidationIssue("recovery_days", "Le plan doit garder au moins un jour recovery/off."))
    if primary_sport_sessions == 0:
        issues.append(ValidationIssue("primary_sport_missing", f"Aucune seance du sport prioritaire {primary_sport}."))
    if key_sessions > allowed_key_sessions:
        issues.append(ValidationIssue("too_many_key_sessions", f"{key_sessions} seances cle alors que {allowed_key_sessions} max sont attendues."))
    if _has_adjacent_hard_sessions(hard_indexes):
        issues.append(ValidationIssue("adjacent_hard_sessions", "Deux seances dures consecutives ont ete placees."))

    # Intensity distribution check (soft warnings)
    mode = getattr(planning_decision, "planning_mode", "maintain_load") if planning_decision else "maintain_load"
    dist_warnings = check_distribution(ordered_days, mode)
    for warning in dist_warnings:
        issues.append(ValidationIssue("intensity_distribution", warning, severity="warning"))

    blocking_issues = [issue for issue in issues if issue.severity == "error"]
    return ValidationResult(is_valid=not blocking_issues, issues=tuple(issues))


def _is_key_session(day: dict[str, Any]) -> bool:
    priority = str(day.get("priority") or "").strip().lower()
    load_score = int(day.get("load_score") or 0)
    return priority in KEY_PRIORITIES or load_score >= 3


def _is_hard_session(day: dict[str, Any]) -> bool:
    intensity = str(day.get("intensity") or "").strip().lower()
    return intensity in HARD_INTENSITIES or _is_key_session(day)


def _has_adjacent_hard_sessions(hard_indexes: Sequence[int]) -> bool:
    ordered = sorted(set(hard_indexes))
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous == 1:
            return True
    return False
