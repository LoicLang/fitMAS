from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy import conversation_canonical_clarification_bridge as bridge


def test_short_needs_clarification_turn_composes_without_legacy_decide() -> None:
    turn_plan = SimpleNamespace(
        primary_intent="needs_clarification",
        secondary_intents=(),
        user_goal="reponse courte sans fil actif",
        needs_clarification=True,
        clarification_question="Tu veux dire samedi pour quoi exactement ?",
        confidence=0.82,
    )

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "clarification"
            assert outcome.reply_contract.mode == "canonical_clarification"
            assert "plan_committed" in outcome.reply_contract.forbidden_claims
            return SimpleNamespace(text=outcome.explanation.next_step, verified=True)

    turn_context: dict[str, object] = {}

    outcome = bridge.compose_canonical_clarification_reply(
        composer=FakeComposer(),
        user_text="samedi",
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=(),
    )

    assert outcome is not None
    assert outcome.response_mode == "canonical_clarification"
    assert outcome.mutation_applied is False
    assert turn_context["legacy_decide"]["legacy_skipped"] is True
    assert turn_context["canonical_clarification"]["composed"] is True


def test_clarification_bridge_rejects_non_clarification_turn() -> None:
    turn_plan = SimpleNamespace(
        primary_intent="plan_lookup",
        secondary_intents=(),
        needs_clarification=False,
        confidence=0.9,
    )

    assert (
        bridge.compose_canonical_clarification_reply(
            composer=SimpleNamespace(),
            user_text="redonne le plan",
            turn_plan=turn_plan,
            turn_context={},
            grounding_facts=(),
        )
        is None
    )
