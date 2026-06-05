from __future__ import annotations

from datetime import datetime, timezone

from fitmas.runtime_v0.meso.context import constraints_from_snapshot, fact_to_constraint
from fitmas.runtime_v0.meso.model import TypedConstraint
from fitmas.runtime_v0.snapshot import FactView, WorldSnapshot
from fitmas.runtime_v0.state import ConversationState

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)


def _fact(kind: str, confidence: float = 0.9, fid: int = 1) -> FactView:
    return FactView(
        id=fid,
        kind=kind,
        text="peu importe le texte",
        confidence=confidence,
        created_at=NOW,
        expires_at=None,
    )


def _snapshot(facts: tuple[FactView, ...]) -> WorldSnapshot:
    return WorldSnapshot(
        user_id=1,
        today=NOW.date(),
        now=NOW,
        timezone="UTC",
        objective=None,
        current_plan=(),
        recent_plan=(),
        recent_activities=(),
        active_facts=facts,
        active_pending=None,
        recent_execution_events=(),
        recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


def test_health_fact_maps_to_conservative_constraint():
    # Conservative bridge: a health fact restricts intensity (blocks hard) —
    # the current runtime behaviour, no text parsing, no regression.
    constraint = fact_to_constraint(_fact("health", 0.9))
    assert constraint == TypedConstraint(
        severity="moderate", restricts=("intensity",), active=True
    )


def test_non_health_fact_maps_to_none():
    assert fact_to_constraint(_fact("preference", 0.9)) is None
    assert fact_to_constraint(_fact("availability", 0.9)) is None
    assert fact_to_constraint(_fact("constraint", 0.9)) is None


def test_low_confidence_health_is_ignored():
    # Mirrors sport_rules: only confidence >= 0.5 gates.
    assert fact_to_constraint(_fact("health", 0.4)) is None


def test_constraints_from_snapshot_keeps_only_active_health():
    snapshot = _snapshot(
        (
            _fact("health", 0.9, 1),
            _fact("preference", 0.9, 2),
            _fact("health", 0.4, 3),
        )
    )
    constraints = constraints_from_snapshot(snapshot)
    assert len(constraints) == 1
    assert constraints[0].restricts == ("intensity",)
