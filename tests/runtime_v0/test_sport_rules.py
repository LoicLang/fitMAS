from __future__ import annotations

from datetime import date, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.proposals import PlanPatchDraft, PlanPatchOperation
from fitmas.runtime_v0.snapshot import FactView, SessionView, WorldSnapshot
from fitmas.runtime_v0.state import ConversationState


PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 5, 22)
NOW = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)


def _sport_rules():
    assert find_spec("fitmas.runtime_v0.sport_rules") is not None
    return import_module("fitmas.runtime_v0.sport_rules")


def _session(
    session_id: int,
    *,
    offset: int,
    intensity: str = "easy",
    priority: str = "secondary",
    status: str = "planned",
    duration_min: int = 45,
) -> SessionView:
    return SessionView(
        id=session_id,
        date=TODAY + timedelta(days=offset),
        sport="run",
        title=f"Session {session_id}",
        duration_min=duration_min,
        intensity_label=intensity,
        priority=priority,
        status=status,
    )


def _snapshot(
    sessions: tuple[SessionView, ...],
    *,
    facts: tuple[FactView, ...] = (),
) -> WorldSnapshot:
    return WorldSnapshot(
        user_id=1,
        today=TODAY,
        now=NOW,
        timezone="Europe/Paris",
        objective=None,
        current_plan=sessions,
        recent_plan=(),
        recent_activities=(),
        active_facts=facts,
        active_pending=None,
        recent_execution_events=(),
        recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


def test_done_source_is_blocked():
    sport_rules = _sport_rules()
    snapshot = _snapshot((_session(60, offset=0, status="done"),))
    draft = PlanPatchDraft(
        operations=(PlanPatchOperation(kind="move", source_session_id=60, target_date=TODAY + timedelta(days=2)),),
        rationale="move done",
    )

    decision = sport_rules.evaluate_plan_patch_sport_rules(draft, snapshot)

    assert decision.action == "block"
    assert decision.reason == "done_session_protected"


def test_hard_session_next_to_hard_is_blocked():
    sport_rules = _sport_rules()
    snapshot = _snapshot(
        (
            _session(60, offset=0, intensity="hard"),
            _session(61, offset=1, intensity="hard"),
        )
    )
    draft = PlanPatchDraft(
        operations=(PlanPatchOperation(kind="move", source_session_id=60, target_date=TODAY + timedelta(days=2)),),
        rationale="move hard",
    )

    decision = sport_rules.evaluate_plan_patch_sport_rules(draft, snapshot)

    assert decision.action == "block"
    assert decision.reason == "hard_session_too_dense"


def test_health_fact_blocks_new_hard():
    sport_rules = _sport_rules()
    snapshot = _snapshot(
        (_session(60, offset=0, intensity="easy"),),
        facts=(
            FactView(
                id=1,
                kind="health",
                text="Fatigue severe active",
                confidence=0.9,
                created_at=NOW,
                expires_at=NOW + timedelta(days=2),
            ),
        ),
    )
    draft = PlanPatchDraft(
        operations=(
            PlanPatchOperation(
                kind="replace",
                source_session_id=60,
                new_intensity_label="hard",
                new_duration_min=50,
            ),
        ),
        rationale="make hard",
    )

    decision = sport_rules.evaluate_plan_patch_sport_rules(draft, snapshot)

    assert decision.action == "block"
    assert decision.reason == "health_fact_blocks_hard"


def test_key_and_multi_operation_require_confirmation():
    sport_rules = _sport_rules()
    snapshot = _snapshot(
        (
            _session(60, offset=0, priority="key"),
            _session(61, offset=1, priority="secondary"),
        )
    )

    key = sport_rules.evaluate_plan_patch_sport_rules(
        PlanPatchDraft(
            operations=(PlanPatchOperation(kind="move", source_session_id=60, target_date=TODAY + timedelta(days=2)),),
            rationale="move key",
        ),
        snapshot,
    )
    multi = sport_rules.evaluate_plan_patch_sport_rules(
        PlanPatchDraft(
            operations=(
                PlanPatchOperation(kind="move", source_session_id=60, target_date=TODAY + timedelta(days=2)),
                PlanPatchOperation(kind="lighten", source_session_id=61, new_intensity_label="easy"),
            ),
            rationale="multi",
        ),
        snapshot,
    )

    assert key.action == "pending"
    assert key.reason == "key_session_requires_confirmation"
    assert multi.action == "pending"
    assert multi.reason == "multi_operation_requires_confirmation"


def test_single_swap_requires_confirmation():
    sport_rules = _sport_rules()
    snapshot = _snapshot(
        (
            _session(60, offset=0, priority="secondary"),
            _session(61, offset=1, priority="secondary"),
        )
    )

    decision = sport_rules.evaluate_plan_patch_sport_rules(
        PlanPatchDraft(
            operations=(PlanPatchOperation(kind="swap", source_session_id=60, target_session_id=61),),
            rationale="échanger les deux séances faciles",
        ),
        snapshot,
    )

    assert decision.action == "pending"
    assert decision.reason == "swap_requires_confirmation"


def test_single_secondary_move_still_auto_commits():
    sport_rules = _sport_rules()
    snapshot = _snapshot(
        (
            _session(60, offset=0, priority="secondary"),
            _session(61, offset=1, priority="secondary"),
        )
    )

    decision = sport_rules.evaluate_plan_patch_sport_rules(
        PlanPatchDraft(
            operations=(PlanPatchOperation(kind="move", source_session_id=60, target_date=TODAY + timedelta(days=2)),),
            rationale="déplacer une séance secondaire",
        ),
        snapshot,
    )

    assert decision.action == "allow"
    assert decision.reason == "low_risk_plan_patch"
