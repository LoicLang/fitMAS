from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.coach_decision_provider import (
    CoachDecisionRequest,
    LegacyCoachDecisionProvider,
)


def _request() -> CoachDecisionRequest:
    return CoachDecisionRequest(
        user_text="J'ai pas eu le temps hier",
        plan_summary="",
        timeline_summary="timeline",
        execution_summary="execution",
        temporal_summary="temporal",
        activity_claim_summary="claim",
        signal_summary="signal",
        conversation_history=[{"role": "user", "text": "avant"}],
        coach_context={"turn_primary_intent": "execution_report"},
        remembered_facts=[{"key": "health:knee"}],
        time_context={"today": "2026-05-15"},
        tool_context=SimpleNamespace(pipeline="conversation"),
    )


def test_provider_clears_decide_none_and_forwards_request() -> None:
    calls: list[tuple[str, object]] = []
    returned = SimpleNamespace(response_type="no_change", fitmas_message="ok")

    def clear() -> None:
        calls.append(("clear", None))

    def decide(*args, **kwargs):
        calls.append(("decide_args", args))
        calls.append(("decide_kwargs", kwargs))
        return returned

    provider = LegacyCoachDecisionProvider(decide_fn=decide, clear_fn=clear)

    result = provider.decide(_request())

    assert result.raw_decision is returned
    assert result.decision is returned
    assert result.artifact.kind == "coach_decision"
    assert result.artifact.response_type == "no_change"
    assert result.artifact.reply_hint == "ok"
    assert result.source == "legacy_coach_decision"
    assert calls[0] == ("clear", None)
    assert calls[1][1][0] == "J'ai pas eu le temps hier"
    assert calls[2][1]["coach_context"]["turn_primary_intent"] == "execution_report"
    assert calls[2][1]["tool_context"].pipeline == "conversation"


def test_provider_records_exception_without_raising() -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("provider down")

    provider = LegacyCoachDecisionProvider(decide_fn=broken, clear_fn=lambda: None)

    result = provider.decide(_request())

    assert result.raw_decision is None
    assert result.decision is None
    assert result.artifact.kind == "none"
    assert result.error_type == "RuntimeError"
    assert "provider down" in str(result.error_message)
