from __future__ import annotations

import asyncio

from fitmas.coach_messages import CoachDraft
from fitmas.skills.heartbeat.runtime_adapter import HeartbeatRuntimeResult, run_heartbeat_trigger


def test_heartbeat_draft_factory_routes_through_runtime_by_default(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    draft = CoachDraft(text="Legacy draft", proactive=True)
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        calls.append(kwargs)
        return run_heartbeat_trigger(**kwargs)

    monkeypatch.delenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", raising=False)
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory("morning_briefing", lambda: draft)

    assert factory() is draft
    assert calls[0]["trigger"] == "morning_briefing"


def test_heartbeat_draft_factory_routes_through_runtime_when_cutover_on(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    draft = CoachDraft(text="Runtime draft", proactive=True)
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        calls.append(kwargs)
        return run_heartbeat_trigger(**kwargs)

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "1")
    monkeypatch.delenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", raising=False)
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory(
        "morning_briefing",
        lambda: draft,
        metadata={"window_status": "catchup"},
    )

    assert factory() is draft
    assert calls[0]["trigger"] == "morning_briefing"
    assert calls[0]["source"] == "scheduler"
    assert calls[0]["delivery_channel"] == "telegram"
    assert calls[0]["metadata"] == {"window_status": "catchup"}


def test_heartbeat_draft_factory_enforced_verifier_can_suppress_draft(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    draft = CoachDraft(text="Runtime draft", proactive=True)

    def fake_run(**kwargs) -> HeartbeatRuntimeResult:
        assert kwargs["enforce_verifier"] is True
        result = run_heartbeat_trigger(**kwargs)
        return HeartbeatRuntimeResult(
            event=result.event,
            outcome=result.outcome,
            draft=None,
            reply_text=None,
            verifier_reason="blocked",
        )

    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "true")
    monkeypatch.setenv("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE", "1")
    monkeypatch.setattr(adapter, "run_heartbeat_trigger", fake_run)

    factory = scheduler._heartbeat_draft_factory("weekly_review", lambda: draft)

    assert factory() is None


def test_send_serialized_draft_persists_only_after_successful_send(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler

    sent: list[tuple[int, str, str]] = []
    persisted: list[CoachDraft] = []
    guarded: list[bool] = []
    draft = CoachDraft(text="Send me", proactive=True)

    class Bot:
        async def send_message(self, *, chat_id: int, text: str, parse_mode: str) -> None:
            sent.append((chat_id, text, parse_mode))

    class Context:
        bot = Bot()

    monkeypatch.setattr(scheduler, "persist_draft_for_owner", lambda value: persisted.append(value))
    monkeypatch.setattr(scheduler, "_reserve_heartbeat_guard_after_send", lambda: guarded.append(True))

    asyncio.run(
        scheduler._send_serialized_draft(
            Context(),
            chat_id=123,
            draft_factory=lambda: draft,
            empty_log_message="empty",
        )
    )

    assert sent == [(123, "Send me", "Markdown")]
    assert persisted == [draft]
    assert guarded == [True]


def test_send_serialized_draft_does_not_persist_after_failed_send(monkeypatch) -> None:
    from fitmas.app.telegram import scheduler

    persisted: list[CoachDraft] = []
    guarded: list[bool] = []
    draft = CoachDraft(text="Send me", proactive=True)

    class Bot:
        async def send_message(self, *, chat_id: int, text: str, parse_mode: str) -> None:
            raise RuntimeError("telegram down")

    class Context:
        bot = Bot()

    monkeypatch.setattr(scheduler, "persist_draft_for_owner", lambda value: persisted.append(value))
    monkeypatch.setattr(scheduler, "_reserve_heartbeat_guard_after_send", lambda: guarded.append(True))

    try:
        asyncio.run(
            scheduler._send_serialized_draft(
                Context(),
                chat_id=123,
                draft_factory=lambda: draft,
                empty_log_message="empty",
            )
        )
    except RuntimeError:
        pass

    assert persisted == []
    assert guarded == []
