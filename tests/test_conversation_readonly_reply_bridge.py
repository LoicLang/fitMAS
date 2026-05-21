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
    assert reply == "Bien recu. Rien ne bouge dans le plan sur ce tour."
    assert mode == "canonical_no_action_safe_reply"
