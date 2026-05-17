from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.legacy.conversation_coach_decision_reply_bridge import compose_coach_decision_reply


def test_reply_bridge_uses_confirmation_reason_before_message() -> None:
    outcome = compose_coach_decision_reply(
        db=None,
        user=SimpleNamespace(id=1),
        user_text="ok",
        decision_artifact=legacy_decision_artifact_from_raw(SimpleNamespace(
            response_type="requires_confirmation",
            confirmation_reason="Tu confirmes ?",
            fitmas_message="Brouillon",
        )),
        turn_context={"turn_plan": {"primary_intent": "plan_mutation"}},
        grounding=None,
        action_result={},
        compose_no_change_reply_for_turn_fn=None,
    )

    assert outcome.reply_text == "Tu confirmes ?"
    assert outcome.response_mode == "requires_confirmation"
    assert outcome.mutation_applied is False


def test_reply_bridge_routes_no_change_through_composer() -> None:
    calls = []

    def compose_no_change_reply_for_turn_fn(**kwargs):
        calls.append(kwargs)
        return "Reply composee", "no_change_composed"

    outcome = compose_coach_decision_reply(
        db=object(),
        user=SimpleNamespace(id=1),
        user_text="redonne le plan",
        decision_artifact=legacy_decision_artifact_from_raw(SimpleNamespace(
            response_type="no_change",
            confirmation_reason=None,
            fitmas_message="Brouillon legacy",
        )),
        turn_context={"turn_plan": {"primary_intent": "plan_lookup"}},
        grounding=SimpleNamespace(),
        action_result={"memory_applied": 0},
        compose_no_change_reply_for_turn_fn=compose_no_change_reply_for_turn_fn,
    )

    assert outcome.reply_text == "Reply composee"
    assert outcome.response_mode == "no_change_composed"
    assert calls[0]["original_reply"] == "Brouillon legacy"
