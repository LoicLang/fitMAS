from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.proposals import (
    ActionProposal,
    MemoryFactDraft,
    PlanPatchDraft,
    PlanPatchOperation,
    proposal_from_dict,
    proposal_to_dict,
)
from fitmas.runtime_v0.snapshot import SnapshotBuilder
from fitmas.runtime_v0.tools_proposal import (
    ask_clarification,
    propose_execution_correction,
    propose_execution_update,
    propose_memory_update,
    propose_plan_patch,
)
from fitmas.runtime_v0.tools_read import ToolContext


PARIS = ZoneInfo("Europe/Paris")


def _context(tmp_path) -> ToolContext:
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    init_db(db_path)
    return ToolContext(db_path=db_path, snapshot=SnapshotBuilder(db_path).build(1, now), scratchpad={})


def _counts(ctx: ToolContext) -> dict[str, int]:
    tables = (
        "v0_command_events",
        "v0_facts",
        "v0_pending_confirmations",
        "v0_scheduled_sessions",
    )
    with connect(ctx.db_path) as connection:
        return {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in tables
        }


def test_proposal_tools_return_typed_proposals_without_writes(tmp_path):
    ctx = _context(tmp_path)
    before = _counts(ctx)

    execution = propose_execution_update(
        ctx,
        session_id=66,
        status="skipped",
        evidence="user said skipped yesterday",
    )
    correction = propose_execution_correction(
        ctx,
        previous_event_id=17,
        correct_session_id=66,
        correct_status="done",
        duration_min=25,
        evidence="user corrected previous execution",
    )
    patch = propose_plan_patch(
        ctx,
        operations=[
            {
                "kind": "move",
                "source_session_id": 60,
                "target_date": "2026-05-24",
            }
        ],
        rationale="move requested by user",
    )
    memory = propose_memory_update(
        ctx,
        kind="constraint",
        text="Piscine indisponible deux semaines",
        confidence=0.8,
        expires_at="2026-06-05T00:00:00+02:00",
    )
    clarification = ask_clarification(
        ctx,
        question="Quelle séance veux-tu déplacer ?",
        unresolved_intent={
            "type": "move_session",
            "target_date": "2026-05-24",
            "missing": ["source_ref"],
        },
    )

    assert execution.type == "execution_update"
    assert execution.execution_update is not None
    assert correction.type == "execution_correction"
    assert correction.execution_correction is not None
    assert patch.type == "plan_patch"
    assert patch.plan_patch is not None
    assert memory.type == "memory_update"
    assert memory.memory_updates[0].expires_at is not None
    assert clarification.type == "ask_clarification"
    assert clarification.unresolved_intent == {
        "type": "move_session",
        "target_date": "2026-05-24",
        "missing": ["source_ref"],
    }
    assert _counts(ctx) == before


def test_action_proposal_round_trips_dates_and_datetimes():
    expires_at = datetime(2026, 6, 5, tzinfo=PARIS)
    operation = PlanPatchOperation(
        kind="move",
        source_session_id=60,
        target_date=expires_at.date(),
    )
    proposal = ActionProposal(
        type="plan_patch",
        confidence=0.9,
        user_intent_summary="move recovery session",
        evidence=("user asked to move it",),
        plan_patch=PlanPatchDraft(operations=(operation,), rationale="move requested"),
        unresolved_intent={"target_date": "2026-05-24"},
        memory_updates=(
            MemoryFactDraft(
                kind="constraint",
                text="Piscine indisponible",
                confidence=0.8,
                expires_at=expires_at,
            ),
        ),
    )

    data = proposal_to_dict(proposal)
    restored = proposal_from_dict(data)

    assert restored.type == "plan_patch"
    assert restored.plan_patch is not None
    assert restored.plan_patch.operations[0].target_date.isoformat() == "2026-06-05"
    assert restored.memory_updates[0].expires_at == expires_at
    assert restored.unresolved_intent == {"target_date": "2026-05-24"}


def test_plan_patch_normalizes_typed_provider_values(tmp_path):
    ctx = _context(tmp_path)

    proposal = propose_plan_patch(
        ctx,
        operations=[
            {
                "kind": "replace",
                "source_session_id": 71,
                "target_date": "tomorrow",
                "new_sport": "vélo",
                "new_intensity_label": "facile",
            }
        ],
        rationale="replace with easy bike",
    )

    assert proposal.plan_patch is not None
    operation = proposal.plan_patch.operations[0]
    assert operation.target_date is None
    assert operation.new_sport == "bike"
    assert operation.new_intensity_label == "easy"
