"""Deterministic week verifier for the V0 sport engine.

Holds authority on SAFETY + STRUCTURE only — numbers and enums, never free prose.
Quality/personalization is owned by the LLM and confirmed by the human at pending
(all Meso output is pending). See the Slice 0+1 spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fitmas.runtime_v0.meso.model import PlannedWeek, TypedConstraint, WeekTarget

Mode = Literal["continuity", "transition"]
SeverityLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str  # structured message for the regeneration loop
    severity: SeverityLevel


@dataclass(frozen=True)
class WeekVerdict:
    ok: bool
    violations: tuple[Violation, ...]
    requires_pending: bool = True  # Meso never auto-commits


def limits_intensity(constraints: tuple[TypedConstraint, ...]) -> bool:
    """True if an active constraint forbids hard work (restricts intensity or all).

    Such a constraint materially limits the week: the load drop is *explained*, and a
    hard key session can't be prescribed. Driven by pack constraints (typed by the
    runtime at ingestion), not by the generator -> anti-gaming by construction.
    """
    return any(
        constraint.active and ({"intensity", "all"} & set(constraint.restricts))
        for constraint in constraints
    )


def verify_week(
    week: PlannedWeek,
    target: WeekTarget,
    constraints: tuple[TypedConstraint, ...] = (),
    mode: Mode = "continuity",
) -> WeekVerdict:
    violations: list[Violation] = []
    relaxed = limits_intensity(constraints)
    if mode == "continuity":
        if target.phase == "build" and not relaxed:
            violations.extend(_check_key(week, target))
        violations.extend(_check_load_continuity(week, target, drop_relaxed=relaxed))
    else:  # transition: discontinuity + type change allowed, safety enforced
        violations.extend(_check_load_transition(week, target))
    violations.extend(_check_spacing(week))
    violations.extend(_check_health(week, constraints))
    return WeekVerdict(
        ok=not violations,
        violations=tuple(violations),
        requires_pending=True,
    )


def _check_key(week: PlannedWeek, target: WeekTarget) -> list[Violation]:
    quality = [session for session in week.sessions if session.is_quality_key]
    if len(quality) != 1:
        return [
            Violation(
                "key_session_count",
                f"expected exactly 1 quality key session, got {len(quality)}",
                "medium",
            )
        ]
    if quality[0].type != target.key_type:
        return [
            Violation(
                "key_type_drift",
                f"key session type {quality[0].type!r}, prescribed {target.key_type!r}",
                "high",
            )
        ]
    return []


def _check_load_continuity(
    week: PlannedWeek, target: WeekTarget, drop_relaxed: bool = False
) -> list[Violation]:
    low, high = target.load_band
    load = week.week_load
    out: list[Violation] = []
    if load < low and not drop_relaxed:
        out.append(
            Violation("load_drop", f"week load {load} below band min {low}", "high")
        )
    if load > high:
        out.append(
            Violation("load_spike", f"week load {load} above band max {high}", "medium")
        )
    return out


def _check_load_transition(week: PlannedWeek, target: WeekTarget) -> list[Violation]:
    _, high = target.load_band
    load = week.week_load
    if load > high:
        return [
            Violation(
                "unsafe_jump", f"week load {load} above safety ceiling {high}", "high"
            )
        ]
    return []


def _check_spacing(week: PlannedWeek) -> list[Violation]:
    stress = sorted(
        (session for session in week.sessions if session.is_high_stress),
        key=lambda session: session.date,
    )
    for earlier, later in zip(stress, stress[1:]):
        if abs((later.date - earlier.date).days) <= 1:
            return [
                Violation(
                    "hard_back_to_back",
                    f"high-stress sessions on {earlier.date} and {later.date}",
                    "medium",
                )
            ]
    return []


def _check_health(
    week: PlannedWeek, constraints: tuple[TypedConstraint, ...]
) -> list[Violation]:
    out: list[Violation] = []
    has_impact = any(session.is_impact for session in week.sessions)
    has_hard = any(session.is_hard for session in week.sessions)
    for constraint in constraints:
        if not constraint.active:
            continue
        conflict = (
            ("all" in constraint.restricts and has_impact)
            or ("impact" in constraint.restricts and has_impact)
            or ("intensity" in constraint.restricts and has_hard)
        )
        if conflict:
            severity: SeverityLevel = (
                "high" if constraint.severity == "severe" else "medium"
            )
            out.append(
                Violation(
                    "health_conflict",
                    f"active constraint restricts {list(constraint.restricts)}",
                    severity,
                )
            )
    return out
