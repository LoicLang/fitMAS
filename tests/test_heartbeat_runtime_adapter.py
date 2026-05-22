from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fitmas.app.telegram.delivery import CoachDraft, DraftPendingConfirmation
from fitmas.decision import VerificationResult
from fitmas.skills.heartbeat.runtime_adapter import (
    HeartbeatRuntimeResult,
    build_heartbeat_input_event,
    heartbeat_draft_to_outcome,
    run_heartbeat_trigger,
)


class _FakeVerifier:
    def __init__(self, *, allowed: bool, reason: str | None = None) -> None:
        self.allowed = allowed
        self.reason = reason
        self.calls: list[tuple[str, object]] = []

    def verify(self, reply: str, outcome, context) -> VerificationResult:
        self.calls.append((reply, outcome))
        return VerificationResult(allowed=self.allowed, text=reply, reason=self.reason)


def _pending_confirmation() -> DraftPendingConfirmation:
    return DraftPendingConfirmation(
        impact_level="medium",
        reason="La semaine change sensiblement.",
        mutation_type="plan_patch",
        summary="Deplacer la seance qualite a vendredi.",
        source_text="On decale ?",
        decision_json='{"response_type":"plan_patch"}',
    )


def test_build_heartbeat_event_uses_scheduler_source_and_heartbeat_type() -> None:
    occurred_at = datetime(2026, 5, 14, 7, 30, tzinfo=timezone.utc)

    event = build_heartbeat_input_event(
        user_id=42,
        trigger="morning_briefing",
        occurred_at=occurred_at,
        metadata={"window_status": "target_window"},
    )

    assert event.source == "scheduler"
    assert event.type == "heartbeat_tick"
    assert event.text is None
    assert event.occurred_at == occurred_at
    assert event.id.startswith("heartbeat:morning_briefing:")
    assert event.payload == {
        "trigger": "morning_briefing",
        "delivery_channel": "telegram",
        "manual": False,
        "window_status": "target_window",
    }


def test_build_weekly_review_event_uses_weekly_review_type() -> None:
    event = build_heartbeat_input_event(user_id=42, trigger="weekly_review")

    assert event.type == "weekly_review_tick"
    assert event.payload["trigger"] == "weekly_review"


def test_none_draft_maps_to_no_send_outcome() -> None:
    outcome = heartbeat_draft_to_outcome(None, trigger="morning_briefing")

    assert outcome.kind == "no_send"
    assert outcome.explanation.reason_summary == "No proactive message was produced."
    assert outcome.reply_contract.mode == "heartbeat_no_send"
    assert outcome.applied_commands == ()


def test_text_draft_maps_to_answer_outcome() -> None:
    draft = CoachDraft(text="Ce matin, garde le footing facile.", proactive=True)

    outcome = heartbeat_draft_to_outcome(draft, trigger="morning_briefing")

    assert outcome.kind == "answer"
    assert outcome.explanation.decision_label == "Heartbeat ready"
    assert outcome.explanation.reason_summary == draft.text
    assert outcome.reply_contract.mode == "heartbeat_answer"
    assert outcome.reply_contract.forbidden_claims == (
        "plan_committed_without_event",
        "execution_updated_without_event",
    )


def test_pending_draft_maps_to_plan_pending_outcome() -> None:
    draft = CoachDraft(
        text="Je te propose de deplacer la qualite a vendredi. Tu confirmes ?",
        proactive=True,
        pending_confirmation=_pending_confirmation(),
    )

    outcome = heartbeat_draft_to_outcome(draft, trigger="signal_check")

    assert outcome.kind == "plan_pending"
    assert outcome.explanation.reason_summary == "Deplacer la seance qualite a vendredi."
    assert outcome.explanation.next_step == "await_user_confirmation"
    assert outcome.reply_contract.mode == "heartbeat_plan_pending"
    assert outcome.reply_contract.allowed_claims == ("pending_created",)


def test_run_heartbeat_trigger_returns_event_outcome_and_draft_without_side_effects() -> None:
    draft = CoachDraft(text="Petit rappel utile.", proactive=True)

    result = run_heartbeat_trigger(
        trigger="pre_session_reminder",
        legacy_factory=lambda: draft,
        user_id=42,
        occurred_at=datetime(2026, 5, 14, 18, 0, tzinfo=timezone.utc),
    )

    assert isinstance(result, HeartbeatRuntimeResult)
    assert result.event.user_id == 42
    assert result.event.payload["trigger"] == "pre_session_reminder"
    assert result.outcome.kind == "answer"
    assert result.draft is draft
    assert result.reply_text == "Petit rappel utile."

    source = Path("backend/src/fitmas/skills/heartbeat/runtime_adapter.py").read_text(encoding="utf-8")
    forbidden = ("send_message", "persist_draft", "persist_draft_for_owner", "SessionLocal", ".commit(", ".flush(")
    assert [token for token in forbidden if token in source] == []


def test_blocked_verifier_shadow_mode_keeps_draft_and_records_reason() -> None:
    draft = CoachDraft(text="Je cale ca.", proactive=True)
    verifier = _FakeVerifier(allowed=False, reason="uncommitted_action_claim")

    result = run_heartbeat_trigger(
        trigger="morning_briefing",
        legacy_factory=lambda: draft,
        user_id=42,
        verifier=verifier,
        enforce_verifier=False,
    )

    assert result.draft is draft
    assert result.outcome.kind == "answer"
    assert result.verifier_reason == "uncommitted_action_claim"
    assert verifier.calls[0][0] == draft.text


def test_blocked_verifier_enforce_mode_returns_no_send() -> None:
    draft = CoachDraft(text="Je cale ca.", proactive=True)
    verifier = _FakeVerifier(allowed=False, reason="uncommitted_action_claim")

    result = run_heartbeat_trigger(
        trigger="morning_briefing",
        legacy_factory=lambda: draft,
        user_id=42,
        verifier=verifier,
        enforce_verifier=True,
    )

    assert result.draft is None
    assert result.reply_text is None
    assert result.outcome.kind == "no_send"
    assert result.verifier_reason == "uncommitted_action_claim"


def test_allowed_verifier_keeps_draft() -> None:
    draft = CoachDraft(text="Rappel propre.", proactive=True)
    verifier = _FakeVerifier(allowed=True)

    result = run_heartbeat_trigger(
        trigger="weekly_review",
        legacy_factory=lambda: draft,
        user_id=42,
        verifier=verifier,
        enforce_verifier=True,
    )

    assert result.draft is draft
    assert result.reply_text == draft.text
    assert result.outcome.kind == "answer"
    assert result.event.type == "weekly_review_tick"
    assert result.event.occurred_at <= datetime.now(timezone.utc) + timedelta(seconds=2)


def test_runtime_flag_helpers_read_environment(monkeypatch) -> None:
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    monkeypatch.delenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", raising=False)
    assert adapter.heartbeat_runtime_cutover_enabled() is True
    assert adapter.heartbeat_runtime_verifier_enforced() is False

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "0")
    assert adapter.heartbeat_runtime_cutover_enabled() is False

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "yes")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    assert adapter.heartbeat_runtime_cutover_enabled() is True
    assert adapter.heartbeat_runtime_verifier_enforced() is True
