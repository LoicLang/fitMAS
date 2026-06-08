"""Typed Meso (week) model for the V0 sport engine.

Pure domain: no DB, no LLM, no network. The verifier reads this typed skeleton
(numbers + enums); the free `detail` prose is owned by the LLM and never read by
deterministic code. See docs/PLANNING-V0.md and the Slice 0+1 spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Sport = Literal["run"]
SessionType = Literal[
    "rest", "easy_run", "long_run", "threshold", "intervals", "recovery_run"
]
Intensity = Literal["easy", "moderate", "hard"]
Phase = Literal["build", "recovery", "taper"]
Restrict = Literal["intensity", "impact", "all"]
Severity = Literal["mild", "moderate", "severe"]

_INTENSITY_WEIGHT: dict[str, float] = {"easy": 1.0, "moderate": 1.5, "hard": 2.0}
_QUALITY_KEY_TYPES = frozenset({"threshold", "intervals"})

# Continuity bands per phase: (min, max) as a fraction of last week's real load.
_PHASE_BANDS: dict[str, tuple[float, float]] = {
    "build": (1.00, 1.10),
    "recovery": (0.50, 0.70),
    "taper": (0.40, 0.60),
}


@dataclass(frozen=True)
class TypedSession:
    date: date
    type: SessionType
    duration_min: int
    intensity: Intensity
    sport: Sport = "run"
    detail: str = ""  # free prose — NEVER read by the verifier

    @property
    def load(self) -> float:
        if self.type == "rest":
            return 0.0
        return self.duration_min * _INTENSITY_WEIGHT[self.intensity]

    @property
    def is_quality_key(self) -> bool:
        return self.type in _QUALITY_KEY_TYPES

    @property
    def is_hard(self) -> bool:
        """Intensity load: a quality session or an explicitly hard effort."""
        return self.is_quality_key or self.intensity == "hard"

    @property
    def is_high_stress(self) -> bool:
        """Overall stress, volume included (a long run is high stress, not hard)."""
        return self.is_hard or self.type == "long_run"

    @property
    def is_impact(self) -> bool:
        return self.type != "rest"  # running: any session that runs is impact


@dataclass(frozen=True)
class PlannedWeek:
    sessions: tuple[TypedSession, ...]

    @property
    def week_load(self) -> float:
        return sum(session.load for session in self.sessions)


@dataclass(frozen=True)
class WeekActuals:
    """Last week (N-1) as actually realized."""

    total_load: float
    key_type: SessionType


@dataclass(frozen=True)
class WeekTarget:
    phase: Phase
    key_type: SessionType  # PRESCRIBED, not chosen by the LLM
    load_band: tuple[float, float]  # (min, max)
    progression_axis: Literal["volume", "intensity"] = "volume"


@dataclass(frozen=True)
class TypedConstraint:
    """Health/availability constraint, typed at ingestion by the runtime LLM."""

    severity: Severity
    restricts: tuple[Restrict, ...]
    active: bool = True  # already filtered for expiry/resolution upstream
    blocked_days: tuple[str, ...] = ()  # weekday names monday..sunday; () = no day block


@dataclass(frozen=True)
class Signal:
    """A recent fact as an advisory hint for the generator (never a gate)."""

    kind: str  # "fatigue" | "soreness" | "preference" — non sur-enumé en V0
    text: str


@dataclass(frozen=True)
class ContextPack:
    """The layered Meso context-pack the generator/verifier consume.

    target/last_week_actuals are None at cold-start (no prior typed week).
    signals is a typed slot left empty in Slice 2.0 (filled in 2.1).
    """

    target: WeekTarget | None
    last_week_actuals: WeekActuals | None
    constraints: tuple[TypedConstraint, ...]
    signals: tuple[Signal, ...] = ()


def derive_continuity_target(actuals: WeekActuals, phase: Phase = "build") -> WeekTarget:
    low, high = _PHASE_BANDS[phase]
    base = actuals.total_load
    return WeekTarget(
        phase=phase,
        key_type=actuals.key_type,  # carry the type (continuity)
        load_band=(round(base * low, 1), round(base * high, 1)),
        progression_axis="volume",
    )


def actuals_from_week(week: PlannedWeek) -> WeekActuals:
    """Reduce a typed week to last-week actuals (forward-only chaining).

    A generated, verified build week has exactly one quality key; the precondition
    holds by construction. Recovery/taper (legitimately 0 key) is out of scope for
    Slice 2.0 — the generator decides the carried key_type then.
    """
    keys = [session for session in week.sessions if session.is_quality_key]
    if len(keys) != 1:
        raise ValueError(
            f"forward-only actuals need exactly one quality key, got {len(keys)}"
        )
    return WeekActuals(total_load=week.week_load, key_type=keys[0].type)
