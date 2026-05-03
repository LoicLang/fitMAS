from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fitmas.conversation_pipeline import (
    _blocked_mutation_reply,
    _blocked_plan_patch_reply,
    _execution_applied_patch_blocked_reply,
)
from fitmas.mutation_permissions import MutationImpactAssessment, build_confirmation_prompt
from fitmas.plan_mutation_service import (
    PlanAppliedMutationEvent,
    PlanBlockedMutationEvent,
    PlanMutationServiceResult,
    PlanPatchServiceResult,
)
from fitmas.plan_patch import PlanPatchOperationValidation, PlanPatchValidation


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
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)

        reply = _blocked_mutation_reply(decision, None)

        self.assertNotIn("Je ne l'ai pas applique", reply)
        self.assertIn("bouger", reply.lower())

    def test_plan_patch_block_uses_suggested_fix_before_internal_reason(self) -> None:
        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(
                status="blocked",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="replace_session",
                        status="blocked",
                        target_session_id=999,
                        block_reason="target_session_not_found",
                        suggested_fix="Relire le planning actuel et cibler une session active.",
                    ),
                ),
            )
        )

        reply = _blocked_plan_patch_reply(result)

        self.assertIn("Relire le planning actuel", reply)
        self.assertNotIn("target_session_not_found", reply)

    def test_plan_patch_block_prefers_final_reply_composer(self) -> None:
        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(
                status="blocked",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="blocked",
                        target_session_id=10,
                        block_reason="protected_recovery_target",
                        suggested_fix="echanger avec vendredi",
                    ),
                ),
            )
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="Je ne l'ecrase pas : ce creneau protege ta recup. On peut echanger avec vendredi.",
        ) as compose:
            reply = _blocked_plan_patch_reply(result)

        self.assertEqual(
            reply,
            "Je ne l'ecrase pas : ce creneau protege ta recup. On peut echanger avec vendredi.",
        )
        self.assertTrue(compose.called)

    def test_plan_patch_applied_prefers_final_reply_composer(self) -> None:
        from fitmas.conversation_pipeline import _applied_plan_patch_reply

        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=()),
            mutation_result=PlanMutationServiceResult(
                plan_id=1,
                applied_count=1,
                attempted_count=1,
                event_count=1,
                applied_events=(
                    PlanAppliedMutationEvent(
                        command_type="move_session",
                        user_visible_summary="Footing deplace au 2099-03-24.",
                        event_id=7,
                        target_session_id=41,
                    ),
                ),
            ),
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="C'est cale : le footing passe au 24 mars, sans toucher au reste.",
        ) as compose:
            reply = _applied_plan_patch_reply(result, fallback="Patch applique.")

        self.assertEqual(reply, "C'est cale : le footing passe au 24 mars, sans toucher au reste.")
        context = compose.call_args.args[0]
        self.assertTrue(context.allowed_to_claim_mutation)
        self.assertIn("Footing deplace", context.committed_events[0])

    def test_execution_applied_patch_block_prefers_final_reply_composer(self) -> None:
        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(
                status="blocked",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="blocked",
                        target_session_id=10,
                        block_reason="target_already_skipped",
                        suggested_fix="Cibler une seance encore planifiee.",
                    ),
                ),
            )
        )
        user = SimpleNamespace(id=1)
        session = SimpleNamespace(session_title="Footing facile", completion_status="skipped")

        with (
            patch("fitmas.conversation_pipeline.repo.get_scheduled_session", return_value=session),
            patch(
                "fitmas.conversation_pipeline.final_reply.compose_final_reply",
                return_value="Footing marque non fait. Je ne deplace rien derriere: il faut une seance encore planifiee.",
            ) as compose,
        ):
            reply = _execution_applied_patch_blocked_reply(
                SimpleNamespace(),
                user=user,
                action_result={"execution_updated_session_ids": [123]},
                service_result=result,
            )

        self.assertEqual(
            reply,
            "Footing marque non fait. Je ne deplace rien derriere: il faut une seance encore planifiee.",
        )
        context = compose.call_args.args[0]
        self.assertFalse(context.allowed_to_claim_mutation)
        self.assertIn("Footing facile notee comme non faite", context.execution_actions_applied[0])
        self.assertEqual(context.blocked_events[0].suggested_fix, "Cibler une seance encore planifiee.")

    def test_mutation_block_prefers_final_reply_composer(self) -> None:
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="move_session",
                block_reason="protected_recovery_target",
                target_session_id=10,
                warnings=("Recuperation protegee.",),
            )
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="Je garde ce creneau en recup. Le bon move, c'est un swap avec vendredi.",
        ) as compose:
            reply = _blocked_mutation_reply(decision, result)

        self.assertEqual(reply, "Je garde ce creneau en recup. Le bon move, c'est un swap avec vendredi.")
        self.assertTrue(compose.called)

    def test_plan_patch_confirmation_prompt_drops_yes_no_protocol(self) -> None:
        from fitmas.conversation_pipeline import _build_plan_patch_confirmation_prompt

        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(
                status="requires_confirmation",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="requires_confirmation",
                        target_session_id=10,
                        block_reason="recovery_tradeoff",
                    ),
                ),
            )
        )

        prompt = _build_plan_patch_confirmation_prompt(result)

        self.assertNotIn("Reponds oui ou non", prompt)
        self.assertIn("confirm", prompt.lower())

    def test_legacy_confirmation_prompt_drops_yes_no_protocol(self) -> None:
        prompt = build_confirmation_prompt(
            SimpleNamespace(mutation_type="move_session"),
            assessment=MutationImpactAssessment(
                level="high",
                requires_confirmation=True,
                reason="moves_key_session",
                summary="deplacement d'une seance cle",
            ),
        )

        self.assertNotIn("Reponds oui ou non", prompt)
        self.assertIn("confirm", prompt.lower())


if __name__ == "__main__":
    unittest.main()
