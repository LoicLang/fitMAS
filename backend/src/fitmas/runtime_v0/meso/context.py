"""Bridge from runtime facts to the typed Meso context (Slice 2.0).

The seam between the conversational runtime (free-text facts) and the Meso
engine (typed constraints). Kept conservative on purpose: a health fact
restricts intensity (blocks hard) — the current runtime behaviour, no text
parsing, no regression. Richer typing (impact vs intensity, severity) is added
at ingestion on proof of drift; this bridge is the stable seam behind which the
deep context engine (PLANNING-V0 Q5) will later plug in.
"""
from __future__ import annotations

from fitmas.runtime_v0.meso.model import (
    ContextPack,
    Phase,
    PlannedWeek,
    TypedConstraint,
    actuals_from_week,
    derive_continuity_target,
)
from fitmas.runtime_v0.snapshot import FactView, WorldSnapshot

# Mirror sport_rules: only a confident health fact gates.
_MIN_HEALTH_CONFIDENCE = 0.5


def fact_to_constraint(fact: FactView) -> TypedConstraint | None:
    """Map one active fact to a typed constraint, or None if it isn't one."""
    if fact.kind != "health" or fact.confidence < _MIN_HEALTH_CONFIDENCE:
        return None
    return TypedConstraint(severity="moderate", restricts=("intensity",), active=True)


def constraints_from_snapshot(snapshot: WorldSnapshot) -> tuple[TypedConstraint, ...]:
    """The constraints layer of the context-pack — health facts always included.

    snapshot.active_facts is already filtered for expiry/resolution, so a
    resolved or expired health fact no longer produces a constraint.
    """
    return tuple(
        constraint
        for fact in snapshot.active_facts
        if (constraint := fact_to_constraint(fact)) is not None
    )


def build_context_pack(
    snapshot: WorldSnapshot,
    prev_week: PlannedWeek | None = None,
    phase: Phase = "build",
) -> ContextPack:
    """Assemble the layered context-pack from a loaded snapshot (pure, no I/O).

    Forward-only: actuals enter by chaining the previous typed week. prev_week is
    None at cold-start -> target/actuals are None (the generator seeds in 2.1).
    signals stays empty in Slice 2.0.
    """
    actuals = actuals_from_week(prev_week) if prev_week is not None else None
    target = derive_continuity_target(actuals, phase) if actuals is not None else None
    return ContextPack(
        target=target,
        last_week_actuals=actuals,
        constraints=constraints_from_snapshot(snapshot),
        signals=(),
    )
