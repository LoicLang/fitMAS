from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.policy import (
    ApplyPlanPatchCommand,
    CorrectSessionStatusCommand,
    CreatePendingConfirmationCommand,
    RuntimePolicy,
    SetSessionStatusCommand,
    UpdateConversationStateCommand,
    UpsertMemoryFactCommand,
)
from fitmas.runtime_v0.proposals import (
    ActionProposal,
    ExecutionCorrectionDraft,
    ExecutionUpdateDraft,
    MemoryFactDraft,
    PlanPatchDraft,
    PlanPatchOperation,
)
from fitmas.runtime_v0.snapshot import SnapshotBuilder


PARIS = ZoneInfo("Europe/Paris")


def _now() -> datetime:
    return datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)


def _snapshot(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = _now()
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_session(connection, session_id=60, offset=0, priority="secondary")
        _insert_session(connection, session_id=61, offset=1, priority="key")
        _insert_session(connection, session_id=50, offset=-1, priority="secondary")
        connection.commit()
    return SnapshotBuilder(db_path).build(1, now)


def _snapshot_for_sport_rules(tmp_path):
    db_path = tmp_path / "fitmas_v0_sport_rules.db"
    now = _now()
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_session(
            connection,
            session_id=60,
            offset=0,
            priority="secondary",
            intensity_label="hard",
            status="planned",
        )
        _insert_session(
            connection,
            session_id=61,
            offset=1,
            priority="secondary",
            intensity_label="hard",
            status="planned",
        )
        _insert_session(
            connection,
            session_id=62,
            offset=2,
            priority="secondary",
            intensity_label="easy",
            status="done",
        )
        connection.commit()
    return SnapshotBuilder(db_path).build(1, now)


def _snapshot_with_health_fact(tmp_path):
    db_path = tmp_path / "fitmas_v0_health_fact.db"
    now = _now()
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_session(
            connection,
            session_id=60,
            offset=0,
            priority="secondary",
            intensity_label="easy",
            status="planned",
        )
        connection.execute(
            """
            insert into v0_facts (
                id, user_id, kind, text, confidence, created_at, expires_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                "health",
                "Fatigue severe active",
                0.9,
                now.isoformat(),
                (now + timedelta(days=2)).isoformat(),
            ),
        )
        connection.commit()
    return SnapshotBuilder(db_path).build(1, now)


def _snapshot_with_execution_event(tmp_path, *, target_id: str = "50", created_offset_hours: int = 1):
    db_path = tmp_path / f"fitmas_v0_event_{target_id}_{created_offset_hours}.db"
    now = _now()
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_session(connection, session_id=50, offset=-1, priority="secondary")
        connection.execute("insert into v0_turns (id) values (?)", ("turn-1",))
        connection.execute(
            """
            insert into v0_command_events (
                id, turn_id, command_type, target_type, target_id,
                status, before_json, after_json, reason, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                17,
                "turn-1",
                "SetSessionStatusCommand",
                "session",
                target_id,
                "applied",
                "{}",
                "{}",
                "execution",
                (now - timedelta(hours=created_offset_hours)).isoformat(),
            ),
        )
        connection.commit()
    return SnapshotBuilder(db_path).build(1, now)


def _snapshot_with_unresolved_intent(tmp_path, intent: dict):
    db_path = tmp_path / "fitmas_v0_intent.db"
    now = _now()
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_session(connection, session_id=60, offset=0, priority="secondary")
        _insert_session(connection, session_id=61, offset=1, priority="key")
        connection.execute(
            """
            insert into v0_conversation_state (
                user_id, last_unresolved_intent_json, expires_at
            ) values (?, ?, ?)
            """,
            (1, json.dumps(intent), (now + timedelta(hours=2)).isoformat()),
        )
        connection.commit()
    return SnapshotBuilder(db_path).build(1, now)


def _insert_session(
    connection,
    *,
    session_id: int,
    offset: int,
    priority: str,
    intensity_label: str = "easy",
    status: str = "planned",
    duration_min: int = 45,
):
    date = (_now().date() + timedelta(days=offset)).isoformat()
    connection.execute(
        """
        insert into v0_scheduled_sessions (
            id, user_id, date, sport, title, duration_min,
            intensity_label, priority, status
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, 1, date, "run", f"Session {session_id}", duration_min, intensity_label, priority, status),
    )


def test_answer_and_no_send_are_readonly(tmp_path):
    snapshot = _snapshot(tmp_path)
    policy = RuntimePolicy()

    answer = policy.evaluate(
        ActionProposal(
            type="answer",
            confidence=0.9,
            user_intent_summary="answer",
            evidence=("read",),
            answer_facts=("2026-05-22 Session 60",),
        ),
        snapshot,
    )
    no_send = policy.evaluate(
        ActionProposal(type="no_send", confidence=0.0, user_intent_summary="none", evidence=()),
        snapshot,
    )

    assert answer.action == "answer_only"
    assert answer.commands == ()
    assert answer.reply_facts == ("2026-05-22 Session 60",)
    assert no_send.action == "no_send"
    assert no_send.commands == ()


def test_ask_clarification_persists_explicit_unresolved_intent(tmp_path):
    snapshot = _snapshot(tmp_path)
    intent = {"type": "move_session", "target_date": "2026-05-24", "missing": ["source_ref"]}

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="ask_clarification",
            confidence=1.0,
            user_intent_summary="clarify",
            evidence=(),
            clarification_question="Quelle séance ?",
            unresolved_intent=intent,
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert isinstance(decision.commands[0], UpdateConversationStateCommand)
    assert decision.commands[0].last_unresolved_intent == intent


def test_ask_clarification_normalizes_move_intent_alias(tmp_path):
    snapshot = _snapshot(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="ask_clarification",
            confidence=1.0,
            user_intent_summary="clarify",
            evidence=(),
            clarification_question="Quelle séance ?",
            unresolved_intent={"type": "plan_patch_move", "target_date": "2026-05-29", "missing": ["source_ref"]},
        ),
        snapshot,
    )

    assert decision.commands[0].last_unresolved_intent == {
        "type": "move_session",
        "target_date": "2026-05-29",
        "missing": ["source_ref"],
    }


def test_ask_clarification_preserves_resolved_fields_from_active_intent(tmp_path):
    snapshot = _snapshot_with_unresolved_intent(
        tmp_path,
        {"type": "move_session", "target_date": "2026-05-29", "missing": ["source_ref"]},
    )

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="ask_clarification",
            confidence=1.0,
            user_intent_summary="clarify",
            evidence=(),
            clarification_question="Quelle séance ?",
            unresolved_intent={"type": "move_session", "missing": ["target_date", "source_ref"]},
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert isinstance(decision.commands[0], UpdateConversationStateCommand)
    assert decision.commands[0].last_unresolved_intent == {
        "type": "move_session",
        "target_date": "2026-05-29",
        "missing": ["source_ref"],
    }


def test_memory_update_allows_valid_facts_and_blocks_too_many_commands(tmp_path):
    snapshot = _snapshot(tmp_path)
    policy = RuntimePolicy()

    decision = policy.evaluate(
        ActionProposal(
            type="memory_update",
            confidence=0.8,
            user_intent_summary="memory",
            evidence=("pool closed",),
            memory_updates=(
                MemoryFactDraft(
                    kind="constraint",
                    text="Piscine fermée",
                    confidence=0.8,
                    expires_at=_now() + timedelta(days=14),
                ),
            ),
        ),
        snapshot,
    )
    too_many = policy.evaluate(
        ActionProposal(
            type="memory_update",
            confidence=0.8,
            user_intent_summary="many memory",
            evidence=("many",),
            memory_updates=tuple(
                MemoryFactDraft(kind="preference", text=f"fact {idx}", confidence=0.8, expires_at=None)
                for idx in range(4)
            ),
        ),
        snapshot,
    )

    assert decision.action == "allow_commit"
    assert isinstance(decision.commands[0], UpsertMemoryFactCommand)
    assert too_many.action == "block"
    assert "too_many_commands" in too_many.reason


def test_execution_update_allows_existing_session_and_compiles_conflict(tmp_path):
    snapshot = _snapshot(tmp_path)
    conflict_snapshot = _snapshot_with_execution_event(tmp_path)
    proposal = ActionProposal(
        type="execution_update",
        confidence=0.8,
        user_intent_summary="skipped",
        evidence=("user said skipped",),
        execution_update=ExecutionUpdateDraft(
            session_id=50,
            status="skipped",
            evidence="user said skipped",
        ),
    )

    decision = RuntimePolicy().evaluate(proposal, snapshot)
    conflict = RuntimePolicy().evaluate(proposal, conflict_snapshot)

    assert decision.action == "allow_commit"
    assert isinstance(decision.commands[0], SetSessionStatusCommand)
    assert decision.commands[0].session_id == 50
    assert conflict.action == "allow_commit"
    assert isinstance(conflict.commands[0], CorrectSessionStatusCommand)


def test_execution_update_on_recent_executed_session_compiles_to_correction(tmp_path):
    snapshot = _snapshot_with_execution_event(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="execution_update",
            confidence=0.8,
            user_intent_summary="did it after all",
            evidence=("user corrected",),
            execution_update=ExecutionUpdateDraft(
                session_id=50,
                status="partial",
                duration_min=25,
                intensity_note="easy",
                evidence="user corrected",
            ),
        ),
        snapshot,
    )

    assert decision.action == "allow_commit"
    assert isinstance(decision.commands[0], CorrectSessionStatusCommand)
    assert decision.commands[0].previous_event_id == 17
    assert decision.commands[0].session_id == 50
    assert decision.commands[0].status == "partial"


def test_execution_correction_requires_recent_previous_event(tmp_path):
    snapshot = _snapshot_with_execution_event(tmp_path)
    policy = RuntimePolicy()

    decision = policy.evaluate(
        ActionProposal(
            type="execution_correction",
            confidence=0.8,
            user_intent_summary="correction",
            evidence=("user corrected",),
            execution_correction=ExecutionCorrectionDraft(
                previous_event_id=17,
                correct_session_id=50,
                correct_status="done",
                duration_min=25,
                evidence="user corrected",
            ),
        ),
        snapshot,
    )
    missing = policy.evaluate(
        ActionProposal(
            type="execution_correction",
            confidence=0.8,
            user_intent_summary="correction",
            evidence=("user corrected",),
            execution_correction=ExecutionCorrectionDraft(
                previous_event_id=999,
                correct_session_id=50,
                correct_status="done",
                evidence="user corrected",
            ),
        ),
        snapshot,
    )

    assert decision.action == "allow_commit"
    assert isinstance(decision.commands[0], CorrectSessionStatusCommand)
    assert decision.commands[0].previous_event_id == 17
    assert missing.action == "block"
    assert missing.reason == "event_not_found"


def test_execution_correction_cannot_retarget_previous_event_even_with_evidence(tmp_path):
    snapshot = _snapshot_with_execution_event(tmp_path, target_id="50")

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="execution_correction",
            confidence=0.8,
            user_intent_summary="correction",
            evidence=("user corrected",),
            execution_correction=ExecutionCorrectionDraft(
                previous_event_id=17,
                correct_session_id=60,
                correct_status="done",
                duration_min=25,
                evidence="user corrected",
            ),
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert decision.reason == "correction_target_mismatch"
    assert decision.commands == ()


def test_plan_patch_commits_low_risk_and_pends_key_or_multi_ops(tmp_path):
    snapshot = _snapshot(tmp_path)
    policy = RuntimePolicy()
    secondary_move = ActionProposal(
        type="plan_patch",
        confidence=0.8,
        user_intent_summary="move secondary",
        evidence=("move",),
        tool_trace=({"name": "get_session", "ok": True},),
        plan_patch=PlanPatchDraft(
            operations=(
                PlanPatchOperation(kind="move", source_session_id=60, target_date=_now().date() + timedelta(days=2)),
            ),
            rationale="move",
        ),
    )
    key_move = ActionProposal(
        type="plan_patch",
        confidence=0.8,
        user_intent_summary="move key",
        evidence=("move",),
        tool_trace=({"name": "get_session", "ok": True},),
        plan_patch=PlanPatchDraft(
            operations=(
                PlanPatchOperation(kind="move", source_session_id=61, target_date=_now().date() + timedelta(days=2)),
            ),
            rationale="move",
        ),
    )
    multi = ActionProposal(
        type="plan_patch",
        confidence=0.8,
        user_intent_summary="multi",
        evidence=("multi",),
        tool_trace=({"name": "get_session", "ok": True},),
        plan_patch=PlanPatchDraft(
            operations=(
                PlanPatchOperation(kind="move", source_session_id=60, target_date=_now().date() + timedelta(days=2)),
                PlanPatchOperation(kind="move", source_session_id=61, target_date=_now().date() + timedelta(days=3)),
            ),
            rationale="multi",
        ),
    )

    allowed = policy.evaluate(secondary_move, snapshot)
    key_pending = policy.evaluate(key_move, snapshot)
    multi_pending = policy.evaluate(multi, snapshot)

    assert allowed.action == "allow_commit"
    assert isinstance(allowed.commands[0], ApplyPlanPatchCommand)
    assert key_pending.action == "create_pending"
    assert isinstance(key_pending.commands[0], CreatePendingConfirmationCommand)
    assert multi_pending.action == "create_pending"


def test_plan_patch_swap_routes_to_pending_never_auto_commits(tmp_path):
    snapshot = _snapshot(tmp_path)
    swap = ActionProposal(
        type="plan_patch",
        confidence=0.8,
        user_intent_summary="swap two sessions",
        evidence=("swap",),
        tool_trace=({"name": "get_session", "ok": True},),
        plan_patch=PlanPatchDraft(
            operations=(
                PlanPatchOperation(kind="swap", source_session_id=60, target_session_id=61),
            ),
            rationale="échanger les deux séances",
        ),
    )

    decision = RuntimePolicy().evaluate(swap, snapshot)

    assert decision.action == "create_pending"
    assert decision.reason == "swap_requires_confirmation"
    assert isinstance(decision.commands[0], CreatePendingConfirmationCommand)
    assert not any(isinstance(command, ApplyPlanPatchCommand) for command in decision.commands)


def test_plan_patch_missing_source_asks_clarification(tmp_path):
    snapshot = _snapshot(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="missing",
            evidence=("missing",),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(kind="move", source_session_id=999, target_date=_now().date()),
                ),
                rationale="missing",
            ),
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert decision.reason == "source_session_not_found"


def test_plan_patch_without_exact_source_read_preserves_target_and_asks_clarification(tmp_path):
    snapshot = _snapshot(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="move",
            evidence=("move",),
            tool_trace=({"name": "get_plan_day", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(
                        kind="move",
                        source_session_id=60,
                        target_date=_now().date() + timedelta(days=2),
                    ),
                ),
                rationale="move",
            ),
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert decision.reason == "plan_patch_source_not_anchored"
    assert isinstance(decision.commands[0], UpdateConversationStateCommand)
    assert decision.commands[0].last_unresolved_intent == {
        "type": "move_session",
        "target_date": "2026-05-24",
        "missing": ["source_ref"],
    }


def test_plan_patch_must_respect_active_unresolved_target_date(tmp_path):
    snapshot = _snapshot_with_unresolved_intent(
        tmp_path,
        {"type": "move_session", "target_date": "2026-05-29", "missing": ["source_ref"]},
    )

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="move",
            evidence=("move",),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(
                        kind="move",
                        source_session_id=60,
                        target_date=_now().date() + timedelta(days=2),
                    ),
                ),
                rationale="move",
            ),
        ),
        snapshot,
    )

    assert decision.action == "ask_clarification"
    assert decision.reason == "unresolved_intent_target_mismatch"
    assert decision.commands == ()


def test_plan_patch_blocks_done_session_mutation(tmp_path):
    snapshot = _snapshot_for_sport_rules(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="move done session",
            evidence=("move",),
            tool_trace=({"name": "get_session", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(
                        kind="move",
                        source_session_id=62,
                        target_date=_now().date() + timedelta(days=4),
                    ),
                ),
                rationale="move done",
            ),
        ),
        snapshot,
    )

    assert decision.action == "block"
    assert decision.reason == "done_session_protected"
    assert decision.commands == ()


def test_plan_patch_blocks_hard_session_next_to_hard_session(tmp_path):
    snapshot = _snapshot_for_sport_rules(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="move hard near hard",
            evidence=("move",),
            tool_trace=({"name": "get_session", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(
                        kind="move",
                        source_session_id=60,
                        target_date=_now().date() + timedelta(days=2),
                    ),
                ),
                rationale="move hard",
            ),
        ),
        snapshot,
    )

    assert decision.action == "block"
    assert decision.reason == "hard_session_too_dense"
    assert decision.commands == ()


def test_plan_patch_blocks_new_hard_when_health_fact_is_active(tmp_path):
    snapshot = _snapshot_with_health_fact(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="make harder",
            evidence=("hard",),
            tool_trace=({"name": "get_session", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(
                    PlanPatchOperation(
                        kind="replace",
                        source_session_id=60,
                        new_intensity_label="hard",
                        new_duration_min=50,
                    ),
                ),
                rationale="make hard",
            ),
        ),
        snapshot,
    )

    assert decision.action == "block"
    assert decision.reason == "health_fact_blocks_hard"
    assert decision.commands == ()


def test_plan_patch_compiles_empty_lighten_to_safe_easy_change(tmp_path):
    snapshot = _snapshot_for_sport_rules(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="lighten",
            evidence=("lighten",),
            tool_trace=({"name": "get_session", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(PlanPatchOperation(kind="lighten", source_session_id=61),),
                rationale="lighten",
            ),
        ),
        snapshot,
    )

    assert decision.action == "allow_commit"
    assert isinstance(decision.commands[0], ApplyPlanPatchCommand)
    operation = decision.commands[0].operations[0]
    assert operation.kind == "lighten"
    assert operation.new_intensity_label == "easy"


def test_plan_patch_blocks_replace_without_effective_payload(tmp_path):
    snapshot = _snapshot(tmp_path)

    decision = RuntimePolicy().evaluate(
        ActionProposal(
            type="plan_patch",
            confidence=0.8,
            user_intent_summary="replace",
            evidence=("replace",),
            tool_trace=({"name": "get_session", "ok": True},),
            plan_patch=PlanPatchDraft(
                operations=(PlanPatchOperation(kind="replace", source_session_id=60),),
                rationale="replace with no payload",
            ),
        ),
        snapshot,
    )

    assert decision.action == "block"
    assert decision.reason == "plan_patch_has_no_effect"
    assert decision.commands == ()


def test_pending_resolution_grounds_against_open_pending():
    from datetime import datetime, timezone
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand, RuntimePolicy
    from fitmas.runtime_v0.proposals import ActionProposal, PendingResolutionDraft
    from fitmas.runtime_v0.snapshot import PendingView, WorldSnapshot
    from fitmas.runtime_v0.state import ConversationState

    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    base = dict(
        user_id=1, today=now.date(), now=now, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=(),
        recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )
    pending = PendingView(id=5, type="week_proposal", summary="semaine du 8 juin", expires_at=now)
    snapshot = WorldSnapshot(active_pending=pending, **base)

    def _proposal(pid, decision):
        return ActionProposal(
            type="pending_resolution", confidence=1.0, user_intent_summary="r",
            evidence=(), pending_resolution=PendingResolutionDraft(pending_id=pid, decision=decision),
        )

    # wrong id -> clarification, no command
    wrong = RuntimePolicy().evaluate(_proposal(99, "accept"), snapshot)
    assert wrong.action == "ask_clarification"
    assert wrong.commands == ()

    # accept -> allow_commit + resolve command, reply carries the week summary
    accept = RuntimePolicy().evaluate(_proposal(5, "accept"), snapshot)
    assert accept.action == "allow_commit"
    assert accept.commands == (ResolvePendingConfirmationCommand(pending_id=5, decision="accept", note=""),)
    assert "semaine du 8 juin" in accept.reply_facts[0]

    # reject -> allow_commit + resolve command
    reject = RuntimePolicy().evaluate(_proposal(5, "reject"), snapshot)
    assert reject.action == "allow_commit"
    assert reject.commands == (ResolvePendingConfirmationCommand(pending_id=5, decision="reject", note=""),)

    # no open pending -> clarification
    no_pending = WorldSnapshot(active_pending=None, **base)
    none = RuntimePolicy().evaluate(_proposal(5, "accept"), no_pending)
    assert none.action == "ask_clarification"


def test_execution_update_blocks_future_done_but_allows_skip_today_and_past(tmp_path):
    # Sessions seeded by _snapshot: 50 = yesterday, 60 = today, 61 = tomorrow.
    # Marking a not-yet-happened session "done"/"partial" is an incoherent state
    # the OutputGuard can't catch (the claim is backed by a real-but-wrong event),
    # so the policy must net it here. Pre-emptive "skipped" stays legitimate.
    snapshot = _snapshot(tmp_path)
    policy = RuntimePolicy()

    def _eval(session_id: int, status: str):
        return policy.evaluate(
            ActionProposal(
                type="execution_update",
                confidence=0.9,
                user_intent_summary="execution",
                evidence=("user reported",),
                execution_update=ExecutionUpdateDraft(
                    session_id=session_id, status=status, evidence="user reported"
                ),
            ),
            snapshot,
        )

    future_done = _eval(61, "done")
    future_partial = _eval(61, "partial")
    future_skipped = _eval(61, "skipped")
    today_done = _eval(60, "done")
    past_done = _eval(50, "done")
    past_skipped = _eval(50, "skipped")

    assert future_done.action == "ask_clarification"
    assert future_done.reason == "future_session_not_completable"
    assert future_done.commands == ()
    assert future_partial.action == "ask_clarification"
    assert future_partial.reason == "future_session_not_completable"

    assert future_skipped.action == "allow_commit"
    assert isinstance(future_skipped.commands[0], SetSessionStatusCommand)
    assert future_skipped.commands[0].status == "skipped"

    assert today_done.action == "allow_commit"
    assert isinstance(today_done.commands[0], SetSessionStatusCommand)
    assert past_done.action == "allow_commit"
    assert isinstance(past_done.commands[0], SetSessionStatusCommand)
    assert past_skipped.action == "allow_commit"
    assert isinstance(past_skipped.commands[0], SetSessionStatusCommand)
