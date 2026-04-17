from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.conversation_pipeline import _blocked_mutation_reply
from fitmas.plan_mutation_service import PlanBlockedMutationEvent, PlanMutationServiceResult


def _service_result_with(event: PlanBlockedMutationEvent) -> PlanMutationServiceResult:
    return PlanMutationServiceResult(
        plan_id=1,
        applied_count=0,
        attempted_count=1,
        event_count=0,
        applied_events=(),
        blocked_events=(event,),
    )


class BlockedMutationReplyTest(unittest.TestCase):
    """When a pre-hook rejects a mutation, the user-facing reply must
    explain WHY so they can adjust their ask, and the next LLM turn has
    a concrete constraint to reason about rather than a vague failure."""

    def test_protected_recovery_target_gets_specific_reply(self) -> None:
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="move_session",
                block_reason="protected_recovery_target",
                target_session_id=10,
            )
        )

        reply = _blocked_mutation_reply(decision, result)

        self.assertIn("recuperation protegee", reply.lower())
        self.assertNotIn("creneau cible n'est pas assez sur", reply)

    def test_same_sport_proximity_gets_specific_reply(self) -> None:
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="move_session",
                block_reason="same_sport_proximity",
                target_session_id=10,
            )
        )

        reply = _blocked_mutation_reply(decision, result)

        self.assertIn("48h", reply)
        self.assertIn("meme sport", reply.lower())

    def test_occupied_training_target_gets_specific_reply(self) -> None:
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="move_session",
                block_reason="occupied_training_target",
                target_session_id=10,
            )
        )

        reply = _blocked_mutation_reply(decision, result)

        self.assertIn("deja une vraie seance", reply.lower())
        self.assertIn("swap", reply.lower())

    def test_unknown_reason_falls_back_to_warning_hint(self) -> None:
        """If the hook introduces a new block_reason we haven't mapped yet,
        surface the first warning message instead of the generic fallback
        — the warning already carries a human-readable hint."""
        decision = SimpleNamespace(mutation_type="replace_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="replace_session",
                block_reason="brand_new_reason_not_mapped",
                target_session_id=10,
                warnings=("Une contrainte future bloque cette mutation.",),
            )
        )

        reply = _blocked_mutation_reply(decision, result)

        self.assertIn("Une contrainte future bloque", reply)

    def test_no_service_result_falls_back_to_generic_move_reply(self) -> None:
        """Legacy call path (no service_result passed) keeps the existing
        move_session fallback so we don't regress existing behavior."""
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)

        reply = _blocked_mutation_reply(decision, None)

        self.assertIn("creneau cible n'est pas assez sur", reply)


if __name__ == "__main__":
    unittest.main()
