from __future__ import annotations

from fitmas.app.telegram.delivery import CoachDraft
from fitmas.skills.heartbeat.runtime_adapter import HeartbeatRuntimeResult, run_heartbeat_trigger


def test_scheduler_cutover_passes_verify_enforcement_and_window_metadata(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    draft = CoachDraft(text="Briefing propre.", proactive=True)
    calls = []

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        calls.append(kwargs)
        return run_heartbeat_trigger(**kwargs)

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "1")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory(
        "morning_briefing",
        lambda: draft,
        metadata={"window_status": "catchup"},
    )

    assert factory() is draft
    assert calls[0]["enforce_verifier"] is True
    assert calls[0]["metadata"] == {"window_status": "catchup"}


def test_scheduler_cutover_suppresses_blocked_draft(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    draft = CoachDraft(text="Je deplace ta seance.", proactive=True)

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        result = run_heartbeat_trigger(**kwargs)
        return HeartbeatRuntimeResult(
            event=result.event,
            outcome=result.outcome,
            draft=None,
            reply_text=None,
            verifier_reason="plan_committed_without_event",
        )

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "1")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory("signal_check", lambda: draft)

    assert factory() is None
