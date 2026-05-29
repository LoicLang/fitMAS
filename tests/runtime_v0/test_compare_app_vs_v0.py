import sqlite3

from scripts.v0_eval.compare_app_vs_v0 import (
    AppOutcome,
    V0Outcome,
    judge_comparison,
    render_report,
    select_turn_ids,
)


def test_judge_comparison_marks_current_state_snapshot_inconclusive():
    verdict = judge_comparison(
        _app(pending_confirmation=True, plan_event_count=0),
        _v0(snapshot_source="current_state", policy_action="create_pending", pending=True),
    )

    assert verdict.winner == "inconclusive_snapshot"
    assert "snapshot_inconclusive" in verdict.risk_flags


def test_judge_comparison_marks_v0_auto_commit_against_app_pending_as_app_better():
    verdict = judge_comparison(
        _app(pending_confirmation=True, plan_event_count=0),
        _v0(command_types=("ApplyPlanPatchCommand",), policy_action="allow_commit"),
    )

    assert verdict.winner == "app_better"
    assert "unsafe_auto_commit" in verdict.risk_flags
    assert "policy_divergence" in verdict.notes


def test_judge_comparison_marks_app_claim_without_event_as_v0_better():
    verdict = judge_comparison(
        _app(reply="C'est fait, j'ai déplacé la séance.", pending_confirmation=False, plan_event_count=0),
        _v0(policy_action="ask_clarification", pending=False, reply="Tu parles de quelle séance ?"),
    )

    assert verdict.winner == "v0_better"
    assert "app_claim_without_event" in verdict.risk_flags


def test_judge_comparison_marks_v0_no_send_when_app_safely_asked_pending_as_app_better():
    verdict = judge_comparison(
        _app(pending_confirmation=True, plan_event_count=0),
        _v0(policy_action="no_send", reply=""),
    )

    assert verdict.winner == "app_better"
    assert "unhelpful_no_send" in verdict.risk_flags


def test_render_report_summarizes_records():
    records = [
        {
            "turn_id": 151,
            "provider": "deepseek",
            "snapshot_source": "conversation_context",
            "winner": "app_better",
            "risk_flags": ["unsafe_auto_commit"],
            "app": {"response_mode": "plan_adaptation_pending_confirmation"},
            "v0": {"policy_action": "allow_commit", "proposal_type": "plan_patch"},
            "notes": ["policy_divergence"],
        },
        {
            "turn_id": 152,
            "provider": "deepseek",
            "snapshot_source": "conversation_context",
            "winner": "v0_better",
            "risk_flags": ["app_claim_without_event"],
            "app": {"response_mode": "reply"},
            "v0": {"policy_action": "ask_clarification", "proposal_type": "ask_clarification"},
            "notes": [],
        },
    ]

    report = render_report(records)

    assert "| app_better | 1 |" in report
    assert "| v0_better | 1 |" in report
    assert "unsafe_auto_commit" in report
    assert "app_claim_without_event" in report


def test_select_turn_ids_ignores_empty_user_messages(tmp_path):
    db_path = tmp_path / "real.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            create table conversation_turns (
                id integer primary key,
                user_id integer,
                user_message text
            )
            """
        )
        connection.executemany(
            "insert into conversation_turns (id, user_id, user_message) values (?, ?, ?)",
            [
                (1, 1, ""),
                (2, 1, "Redonne le plan"),
                (3, 2, "Autre user"),
                (4, 1, "J'ai quoi demain ?"),
            ],
        )

    assert select_turn_ids(db_path, limit=10, user_id=1) == [4, 2]


def _app(
    *,
    reply: str = "Tu confirmes que ça te va ?",
    mutation_applied: bool = False,
    pending_confirmation: bool = False,
    plan_event_count: int = 0,
) -> AppOutcome:
    return AppOutcome(
        turn_id=151,
        user_id=1,
        created_at="2026-05-25T05:50:42+00:00",
        user_message="Échange aujourd’hui et demain s’il te plaît",
        assistant_message=reply,
        response_mode="reply",
        mutation_applied=mutation_applied,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=13 if pending_confirmation else None,
        plan_event_count=plan_event_count,
    )


def _v0(
    *,
    snapshot_source: str = "conversation_context",
    policy_action: str = "ask_clarification",
    proposal_type: str = "ask_clarification",
    command_types: tuple[str, ...] = (),
    pending: bool = False,
    reply: str = "Quelle séance ?",
) -> V0Outcome:
    return V0Outcome(
        provider="deepseek",
        model="test",
        snapshot_source=snapshot_source,
        captured_session_count=2,
        proposal_type=proposal_type,
        policy_action=policy_action,
        command_types=command_types,
        pending=pending,
        reply=reply,
        latency_ms=10,
        tokens_in=0,
        tokens_out=0,
        db_path="/tmp/v0.db",
    )
