from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import readonly_reply as bridge


def test_no_change_bridge_does_not_fallback_to_invalid_analysis_summary(monkeypatch) -> None:
    monkeypatch.setattr(bridge.final_reply, "compose_no_change_reply", lambda **_kwargs: None)

    reply, mode = bridge.compose_no_change_reply_for_turn(
        db=object(),
        user=SimpleNamespace(id=1),
        user_text="je prefere courir le matin",
        original_reply="User expresses a preference for running in the morning when possible.",
        turn_context={"turn_plan": {"primary_intent": "preference_signal"}},
        action_result={},
    )

    assert reply != "User expresses a preference for running in the morning when possible."
    assert reply == "Je le prends en compte. Le planning ne bouge pas pour l'instant."
    assert mode == "canonical_no_action_safe_reply"


def test_execution_report_fallback_uses_applied_execution_fact(monkeypatch) -> None:
    monkeypatch.setattr(bridge.final_reply, "compose_execution_report_reply", lambda **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "execution_action_phrases_for_final_reply",
        lambda *_args, **_kwargs: ("Renfo support du 2026-04-29 notee comme non faite.",),
    )

    reply, mode = bridge.compose_no_change_reply_for_turn(
        db=object(),
        user=SimpleNamespace(id=1),
        user_text="pas eu le temps hier",
        original_reply="Athlete reports not completing yesterday's strength session.",
        turn_context={"turn_plan": {"primary_intent": "execution_report"}},
        action_result={"execution_applied": 1},
    )

    assert reply == "Renfo support du 2026-04-29 notee comme non faite. Le reste du planning ne bouge pas."
    assert mode == "canonical_no_action_safe_reply"
