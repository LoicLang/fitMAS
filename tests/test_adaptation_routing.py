from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.decision.turn_prompt_context import should_route_adaptation_context_to_llm


def _turn_plan(primary: str, *, has_plan_mutation: bool = False) -> SimpleNamespace:
    return SimpleNamespace(primary_intent=primary, has_plan_mutation=has_plan_mutation)


class AdaptationRoutingGateTest(unittest.TestCase):
    """Chantier 1 (autonomy refactor): the routing gate is generalized.

    Any deterministic adaptation candidate is now passed to `decide()` as
    prompt context so the LLM can arbitrate. Direct application without
    LLM arbitration is no longer allowed in conversation turns. The gate
    therefore returns True iff an adaptation candidate exists, regardless
    of the turn planner's intent or the heuristic signal.
    """

    def test_routing_off_when_no_adaptation(self) -> None:
        self.assertFalse(
            should_route_adaptation_context_to_llm(
                _turn_plan("plan_mutation", has_plan_mutation=True),
                None,
                plan_mutation_request=True,
            )
        )
        self.assertFalse(
            should_route_adaptation_context_to_llm(
                None,
                None,
                plan_mutation_request=False,
            )
        )

    def test_routing_on_when_adaptation_present_regardless_of_signal(self) -> None:
        adaptation = object()
        cases = [
            (_turn_plan("plan_mutation", has_plan_mutation=True), True),
            (_turn_plan("plan_mutation", has_plan_mutation=True), False),
            (_turn_plan("recall_check", has_plan_mutation=False), True),
            (_turn_plan("execution_check", has_plan_mutation=False), False),
            (None, True),
            (None, False),
        ]
        for turn_plan, plan_mutation_request in cases:
            with self.subTest(turn_plan=turn_plan, plan_mutation_request=plan_mutation_request):
                self.assertTrue(
                    should_route_adaptation_context_to_llm(
                        turn_plan,
                        adaptation,
                        plan_mutation_request=plan_mutation_request,
                    )
                )


if __name__ == "__main__":
    unittest.main()
