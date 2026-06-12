from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandEvent
from fitmas.runtime_v0.guard import OutputGuard
from fitmas.runtime_v0.policy import PolicyDecision
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.result import build_runtime_result
from fitmas.runtime_v0.snapshot import PendingView


PARIS = ZoneInfo("Europe/Paris")


def _event() -> InputEvent:
    return InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type="user_message",
        text="Plan ?",
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def _result(*, policy_action: str = "answer_only", read_facts=(), committed=(), pending=None):
    return build_runtime_result(
        event=_event(),
        turn_id="turn-1",
        proposal=ActionProposal(
            type="answer",
            confidence=0.8,
            user_intent_summary="answer",
            evidence=tuple(read_facts),
            answer_facts=tuple(read_facts),
        ),
        policy=PolicyDecision(
            action=policy_action,
            reason="test",
            risk_level="low",
            commands=(),
            reply_facts=tuple(read_facts),
        ),
        command_events=tuple(committed),
        pending=pending,
    )


def _committed_event() -> CommandEvent:
    return CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="60",
        status="applied",
        before={},
        after={},
        reason="done",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )


def test_blocks_claim_without_committed_event():
    guard = OutputGuard(today=_event().occurred_at.date())
    result = _result()

    checked = guard.verify("J'ai déplacé la séance.", result)

    assert not checked.ok
    assert "claim_without_event" in checked.blocked_reasons
    assert checked.sanitized_reply


def test_blocks_pending_action_claim():
    guard = OutputGuard(today=_event().occurred_at.date())
    pending = PendingView(1, "plan_patch", "move key", datetime(2026, 5, 23, tzinfo=PARIS))
    result = _result(pending=pending)

    checked = guard.verify("C'est fait, appliqué.", result)

    assert not checked.ok
    assert "pending_action_claim" in checked.blocked_reasons


def test_blocks_internal_jargon_and_meta_opening():
    guard = OutputGuard(today=_event().occurred_at.date())
    result = _result(committed=(_committed_event(),))

    jargon = guard.verify("La policy a validé la mutation.", result)
    meta = guard.verify("L'utilisateur demande son plan.", result)

    assert "internal_jargon" in jargon.blocked_reasons
    assert "meta_opening" in meta.blocked_reasons


def test_blocks_raw_json_and_technical_ids():
    guard = OutputGuard(today=_event().occurred_at.date())
    result = _result(read_facts=('{"sessions": [{"date": "2026-05-23"}]}',))

    raw_json = guard.verify('Session planifiée: {"date": "2026-05-23", "sessions": []}', result)
    technical = guard.verify("La session_id 63 correspond à source_ref.", result)

    assert "raw_json_visible" in raw_json.blocked_reasons
    assert "technical_id_visible" in technical.blocked_reasons


def test_answer_guard_falls_back_to_read_fact_summary_when_reply_is_raw_json():
    guard = OutputGuard(today=_event().occurred_at.date())
    result = _result(
        read_facts=(
            json.dumps(
                {
                    "sessions": [
                        {"date": "2026-05-22", "title": "Footing recup"},
                        {"date": "2026-05-24", "title": "VMA courte"},
                    ]
                }
            ),
        )
    )

    checked = guard.verify('{"sessions": [{"date": "2026-05-22"}]}', result)

    assert not checked.ok
    assert "raw_json_visible" in checked.blocked_reasons
    assert checked.sanitized_reply == "22 Footing recup. 24 VMA courte."


def test_blocks_truncated_reply_endings():
    guard = OutputGuard(today=_event().occurred_at.date())

    checked = guard.verify("Demain tu as une séance avec", _result(read_facts=("demain séance",)))

    assert "truncated_reply" in checked.blocked_reasons


def test_sanitizes_meta_reply_with_committed_execution_summary():
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="CorrectSessionStatusCommand",
        target_type="session",
        target_id="66",
        status="applied",
        before={},
        after={"date": "2026-05-21", "duration_min": 25, "status": "partial"},
        reason="correction",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )

    checked = OutputGuard(date(2026, 5, 22)).verify("L'utilisateur a corrigé.", _result(policy_action="allow_commit", committed=(command,)))

    assert not checked.ok
    assert checked.sanitized_reply == "Corrigé: 25 minutes."


def test_blocks_forbidden_answer_only_date_not_in_read_facts():
    guard = OutputGuard(today=_event().occurred_at.date())
    result = _result(read_facts=("2026-05-22 Footing",))

    checked = guard.verify("Le 2026-05-29 tu cours.", result)

    assert not checked.ok
    assert "unsupported_date" in checked.blocked_reasons


def test_blocks_old_plan_date_unless_present_in_read_facts():
    guard = OutputGuard(today=_event().occurred_at.date())

    blocked = guard.verify("Le 2026-05-01 tu avais vélo.", _result(read_facts=("2026-05-22 Footing",)))
    allowed = guard.verify("Le 2026-05-01 tu avais vélo.", _result(read_facts=("2026-05-01 vélo",)))

    assert "old_plan_date" in blocked.blocked_reasons
    assert allowed.ok


def test_blocks_meta_third_person_mid_sentence():
    # META n'est plus ancré en début de phrase: une fuite "l'utilisateur" au
    # milieu d'une réponse chaleureuse doit aussi être attrapée.
    guard = OutputGuard(today=_event().occurred_at.date())

    checked = guard.verify("Bien noté, je vois que l'utilisateur veut décaler.", _result(committed=(_committed_event(),)))

    assert "meta_opening" in checked.blocked_reasons


def test_blocks_leaked_tool_names():
    guard = OutputGuard(today=_event().occurred_at.date())

    checked = guard.verify("Je vérifie avec get_session puis propose_plan_patch.", _result(committed=(_committed_event(),)))

    assert "internal_jargon" in checked.blocked_reasons


def test_blocks_english_leak():
    guard = OutputGuard(today=_event().occurred_at.date())

    checked = guard.verify("Let me move your session to friday.", _result(committed=(_committed_event(),)))

    assert "english_leak" in checked.blocked_reasons


def test_confirmation_request_without_pending_warns_not_blocks():
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify("Un fractionné en fin de journée, tu me confirmes ?", _result())

    assert result.ok
    assert result.blocked_reasons == ()
    assert result.warnings == ("warn:confirmation_without_pending",)


def test_confirmation_request_with_open_pending_does_not_warn():
    guard = OutputGuard(date(2026, 5, 22), pending_open=True)

    result = guard.verify("Un fractionné en fin de journée, tu me confirmes ?", _result())

    assert result.ok
    assert result.warnings == ()


def test_confirmation_request_with_pending_created_this_turn_does_not_warn():
    pending = PendingView(7, "week_proposal", "semaine du 15 juin", datetime(2026, 5, 23, 14, 0, tzinfo=PARIS))
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify(
        "Je te propose la semaine du 15 juin, tu valides ?",
        _result(policy_action="requires_confirmation", pending=pending),
    )

    assert result.ok
    assert result.warnings == ()


def test_reply_without_confirmation_request_does_not_warn():
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify("Demain c'est footing facile, 35 minutes tranquilles.", _result())

    assert result.ok
    assert result.warnings == ()
