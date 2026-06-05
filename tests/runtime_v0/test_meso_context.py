from __future__ import annotations

from datetime import date, datetime, timezone

from fitmas.runtime_v0.meso.context import (
    build_context_pack,
    constraints_from_snapshot,
    fact_to_constraint,
)
from fitmas.runtime_v0.meso.model import (
    PlannedWeek,
    TypedConstraint,
    TypedSession,
    WeekActuals,
)
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


def test_build_context_pack_cold_start():
    snapshot = _snapshot((_fact("health", 0.9, 1),))
    pack = build_context_pack(snapshot, prev_week=None)
    assert pack.last_week_actuals is None
    assert pack.target is None
    assert len(pack.constraints) == 1
    assert pack.constraints[0].restricts == ("intensity",)
    assert pack.signals == ()


def test_build_context_pack_with_prev_week_derives_target():
    snapshot = _snapshot((_fact("health", 0.9, 1),))
    prev_week = PlannedWeek(
        sessions=(
            TypedSession(date=date(2026, 6, 1), type="easy_run", duration_min=45, intensity="easy"),      # 45
            TypedSession(date=date(2026, 6, 3), type="threshold", duration_min=60, intensity="hard"),     # 120
            TypedSession(date=date(2026, 6, 7), type="long_run", duration_min=90, intensity="moderate"),  # 135
        )
    )
    pack = build_context_pack(snapshot, prev_week=prev_week)
    assert pack.last_week_actuals == WeekActuals(total_load=300.0, key_type="threshold")
    assert pack.target is not None
    assert pack.target.key_type == "threshold"
    assert pack.target.load_band == (300.0, 330.0)  # build 100% -> 110%
    assert len(pack.constraints) == 1
    assert pack.signals == ()


def test_build_context_pack_without_health_fact_has_no_constraint():
    # active_facts is already filtered upstream; a resolved/expired health fact
    # is simply absent -> no constraint in the pack.
    snapshot = _snapshot((_fact("preference", 0.9, 2),))
    pack = build_context_pack(snapshot, prev_week=None)
    assert pack.constraints == ()
    assert pack.signals == ()
