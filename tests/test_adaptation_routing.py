from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.conversation_pipeline import _should_route_adaptation_context_to_llm


def _turn_plan(primary: str, *, has_plan_mutation: bool = False) -> SimpleNamespace:
    return SimpleNamespace(primary_intent=primary, has_plan_mutation=has_plan_mutation)


class AdaptationRoutingGateTest(unittest.TestCase):
    """Close Faille B (adaptation bypass).

    When a deterministic `AdaptationDecision` candidate is produced
    alongside the user's message, the pipeline must decide whether to
    apply it directly or pass it through `decide()` as context so the LLM
    arbitrates. Applying it directly is correct only when the user did
    not explicitly request a plan mutation — otherwise the LLM must get
    the turn so it can reconcile the user's phrasing with the candidate.

    The bypass bug: when the LLM turn-planner crashes (`turn_plan=None`)
    or misclassifies the turn (`primary_intent != "plan_mutation"` and
    `has_plan_mutation=False`), the routing helper returned False and the
    adaptation was applied silently — even when the deterministic
    heuristic had already flagged the message as a plan-mutation request.
    """

    def test_routing_off_when_no_adaptation(self) -> None:
        self.assertFalse(
            _should_route_adaptation_context_to_llm(
                _turn_plan("plan_mutation", has_plan_mutation=True),
                None,
                plan_mutation_request=True,
            )
        )

    def test_routing_on_when_turn_plan_flags_plan_mutation(self) -> None:
        adaptation = object()
        self.assertTrue(
            _should_route_adaptation_context_to_llm(
                _turn_plan("plan_mutation", has_plan_mutation=True),
                adaptation,
                plan_mutation_request=True,
            )
        )

    def test_routing_on_when_heuristic_flags_plan_mutation_but_turn_plan_missing(self) -> None:
        """Classifier crashed -> turn_plan is None, but the deterministic
        heuristic caught a clear mutation verb (decaler, deplacer, etc.).
        The adaptation must NOT bypass decide() silently."""
        adaptation = object()
        self.assertTrue(
            _should_route_adaptation_context_to_llm(
                None,
                adaptation,
                plan_mutation_request=True,
            )
        )

    def test_routing_on_when_heuristic_flags_plan_mutation_but_turn_plan_misclassifies(self) -> None:
        """Classifier returned a non-mutation intent, but the heuristic
        caught the mutation verb. The LLM must still arbitrate."""
        adaptation = object()
        self.assertTrue(
            _should_route_adaptation_context_to_llm(
                _turn_plan("recall_check", has_plan_mutation=False),
                adaptation,
                plan_mutation_request=True,
            )
        )

    def test_routing_off_when_no_plan_mutation_signal_at_all(self) -> None:
        """No heuristic signal and no classifier signal -> safe to apply
        the deterministic adaptation directly (legacy health / life-change
        flow, e.g. 'je suis crame', 'je peux pas ce soir')."""
        adaptation = object()
        self.assertFalse(
            _should_route_adaptation_context_to_llm(
                _turn_plan("execution_check", has_plan_mutation=False),
                adaptation,
                plan_mutation_request=False,
            )
        )
        self.assertFalse(
            _should_route_adaptation_context_to_llm(
                None,
                adaptation,
                plan_mutation_request=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
