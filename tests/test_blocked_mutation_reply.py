from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fitmas.conversation_pipeline import (
    _blocked_mutation_reply,
    _blocked_plan_patch_reply,
    _execution_applied_patch_blocked_reply,
    _plan_patch_service_result_requires_clarification,
)
from fitmas.mutation_permissions import MutationImpactAssessment, build_confirmation_prompt
from fitmas.domain.planning.patch_mutation_service import (
    PlanAppliedMutationEvent,
    PlanBlockedMutationEvent,
    PlanMutationServiceResult,
    PlanPatchServiceResult,
)
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchOperationValidation, PlanPatchValidation
from fitmas.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


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

    def test_legacy_protected_recovery_reason_does_not_surface_protected_language(self) -> None:
        decision = SimpleNamespace(mutation_type="move_session", target_session_id=10)
        result = _service_result_with(
            PlanBlockedMutationEvent(
                command_type="move_session",
                block_reason="protected_recovery_target",
                target_session_id=10,
            )
        )

        reply = _blocked_mutation_reply(decision, result)

        self.assertNotIn("recuperation protegee", reply.lower())
        self.assertNotIn("protected_recovery_target", reply)

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

    def test_ambiguous_target_warning_requires_clarification_not_pending(self) -> None:
        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(
                status="requires_confirmation",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="requires_confirmation",
                        target_session_id=10,
                        warning_codes=("ambiguous_target_reference",),
                        warning_messages=("Plusieurs seances running peuvent correspondre a cette demande."),
                    ),
                ),
            ),
            patch=PlanPatch(
                coach_message="Je peux deplacer la course plus tard.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=10,
                        target_date="2026-05-15",
                        rationale="demande utilisateur ambigue",
                    ),
                ),
            ),
        )

        self.assertTrue(_plan_patch_service_result_requires_clarification(result))

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

    def test_plan_patch_applied_uses_committed_event_summary(self) -> None:
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
        ) as compose, patch(
            "fitmas.conversation_pipeline.final_reply.verify_post_event_reply",
            return_value="C'est cale : le footing passe au 24 mars, sans toucher au reste.",
        ) as verify:
            reply = _applied_plan_patch_reply(result, fallback="Patch applique.")

        self.assertEqual(reply, "Footing deplace au 2099-03-24.")
        self.assertFalse(compose.called)
        self.assertFalse(verify.called)

    def test_plan_patch_applied_ignores_composer_contradiction(self) -> None:
        from fitmas.conversation_pipeline import _applied_plan_patch_reply

        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=()),
            mutation_result=PlanMutationServiceResult(
                plan_id=1,
                applied_count=2,
                attempted_count=2,
                event_count=2,
                applied_events=(
                    PlanAppliedMutationEvent(
                        command_type="replace_session",
                        user_visible_summary="Mercredi remplace par Journee flexible.",
                        event_id=7,
                        target_session_id=41,
                        before_snapshot={
                            "session_title": "Fractionne",
                            "scheduled_date": "2099-03-23",
                            "sport_type": "running",
                            "duration_min": 36,
                        },
                        after_snapshot={
                            "session_title": "Journee flexible",
                            "scheduled_date": "2099-03-23",
                            "sport_type": "rest",
                            "duration_min": 0,
                        },
                    ),
                    PlanAppliedMutationEvent(
                        command_type="replace_session",
                        user_visible_summary="Jeudi remplace par Journee flexible.",
                        event_id=8,
                        target_session_id=42,
                    ),
                ),
            ),
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="J'ai decale le fractionne a jeudi.",
        ), patch(
            "fitmas.conversation_pipeline.final_reply.verify_post_event_reply",
            return_value="J'ai libere mercredi et jeudi en journees flexibles.",
        ) as verify:
            reply = _applied_plan_patch_reply(result, fallback="Patch applique.")

        self.assertEqual(
            reply,
            "Mercredi remplace par Journee flexible. Jeudi remplace par Journee flexible.",
        )
        self.assertFalse(verify.called)

    def test_plan_patch_applied_keeps_event_summary_when_composer_has_wrong_day(self) -> None:
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
                        command_type="replace_session",
                        user_visible_summary="Mardi remplace par Footing easy.",
                        event_id=7,
                        target_session_id=41,
                        before_snapshot={
                            "session_title": "Natation",
                            "scheduled_date": "2026-05-05",
                            "sport_type": "swimming",
                            "duration_min": 40,
                        },
                        after_snapshot={
                            "session_title": "Footing easy",
                            "scheduled_date": "2026-05-05",
                            "sport_type": "running",
                            "duration_min": 35,
                        },
                    ),
                ),
            ),
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="J'ai remplace lundi matin par un footing.",
        ), patch(
            "fitmas.conversation_pipeline.final_reply.verify_post_event_reply",
            return_value="Mardi 5 mai passe en footing easy.",
        ) as verify:
            reply = _applied_plan_patch_reply(result, fallback="Patch applique.")

        self.assertEqual(reply, "Mardi remplace par Footing easy.")
        self.assertFalse(verify.called)

    def test_plan_patch_applied_falls_back_to_event_summary_when_verifier_fails(self) -> None:
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
                        command_type="replace_session",
                        user_visible_summary="Mercredi remplace par Journee flexible.",
                        event_id=7,
                        target_session_id=41,
                    ),
                ),
            ),
        )

        with patch(
            "fitmas.conversation_pipeline.final_reply.compose_final_reply",
            return_value="J'ai decale le fractionne a jeudi.",
        ), patch(
            "fitmas.conversation_pipeline.final_reply.verify_post_event_reply",
            return_value=None,
        ):
            reply = _applied_plan_patch_reply(result, fallback="Patch applique.")

        self.assertEqual(reply, "Mercredi remplace par Journee flexible.")

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

    def test_plan_patch_confirmation_prompt_passes_patch_details_to_composer(self) -> None:
        from fitmas.conversation_pipeline import _build_plan_patch_confirmation_prompt

        result = PlanPatchServiceResult(
            patch=PlanPatch(
                coach_message="La recuperation mobilite passe au lundi 11.",
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=3,
                        target_date="2026-05-11",
                        rationale="Recup mobilite decalee au lundi.",
                    )
                ],
            ),
            validation=PlanPatchValidation(
                status="valid",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="valid",
                        target_session_id=3,
                    ),
                ),
            ),
            week_policy_status="requires_confirmation",
            week_review=WeekCoherenceReview(
                status="requires_confirmation",
                sport_quality="fragile",
                confidence=0.8,
                summary="Patch possible mais fragile sportivement; confirmation requise.",
                findings=(),
                suggested_adjustments=(),
                recommended_policy="confirm_original",
            ),
        )

        captured_contexts = []

        def fake_compose(context):
            captured_contexts.append(context)
            return "Je peux la passer au lundi 11, mais je veux ton feu vert avant de bouger cette recuperation."

        with (
            patch("fitmas.conversation_pipeline.final_reply.compose_final_reply", side_effect=fake_compose),
            patch(
                "fitmas.conversation_pipeline.final_reply.verify_uncommitted_reply",
                side_effect=lambda reply, context, **_kwargs: reply,
            ),
        ):
            reply = _build_plan_patch_confirmation_prompt(result)

        self.assertIn("lundi 11", reply)
        self.assertTrue(captured_contexts)
        facts = "\n".join(captured_contexts[0].extra_facts)
        self.assertIn("move_session", facts)
        self.assertIn("target_session_id=3", facts)
        self.assertIn("target_date=2026-05-11", facts)

    def test_plan_patch_confirmation_verifier_receives_patch_rationale_as_grounding(self) -> None:
        from datetime import date

        from fitmas.conversation_pipeline import _build_plan_patch_confirmation_prompt
        from fitmas.grounding_contract import ReplyGroundingPacket

        result = PlanPatchServiceResult(
            patch=PlanPatch(
                coach_message="Je peux remplacer la natation par du vélo facile.",
                operations=[
                    PlanPatchOperation(
                        operation_type="replace_session",
                        target_session_id=8,
                        new_sport_type="cycling",
                        new_session_type="easy",
                        new_duration_min=35,
                        new_intensity="easy",
                        rationale="douleur epaule quand il nage",
                    )
                ],
            ),
            validation=PlanPatchValidation(
                status="requires_confirmation",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="replace_session",
                        status="requires_confirmation",
                        target_session_id=8,
                    ),
                ),
            ),
        )
        grounding = ReplyGroundingPacket(local_date=date(2026, 5, 10), timezone_name="Europe/Paris")
        captured = {}

        def fake_verify(reply, *, grounding, pipeline_capability):
            captured["grounding"] = grounding
            captured["pipeline_capability"] = pipeline_capability
            return reply

        with (
            patch(
                "fitmas.conversation_pipeline.final_reply.compose_final_reply",
                return_value="Je peux remplacer la natation par du vélo facile pour éviter l'épaule. Tu confirmes ?",
            ),
            patch(
                "fitmas.conversation_pipeline.final_reply.verify_uncommitted_reply",
                side_effect=lambda reply, context, **_kwargs: reply,
            ),
            patch("fitmas.conversation_pipeline.final_reply.verify_factual_reply", side_effect=fake_verify),
        ):
            reply = _build_plan_patch_confirmation_prompt(result, grounding=grounding)

        self.assertIn("vélo facile", reply)
        self.assertEqual(captured["pipeline_capability"], "plan_patch_confirmation")
        extra_facts = "\n".join(captured["grounding"].extra_facts)
        self.assertIn("douleur epaule", extra_facts)
        self.assertIn("new_sport_type=cycling", extra_facts)

    def test_plan_patch_confirmation_rechecks_uncommitted_shape_after_factual_repair(self) -> None:
        from datetime import date

        from fitmas.conversation_pipeline import _build_plan_patch_confirmation_prompt
        from fitmas.grounding_contract import ReplyGroundingPacket

        result = PlanPatchServiceResult(
            patch=PlanPatch(
                coach_message="Je peux déplacer la mobilité à lundi.",
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=3,
                        target_date="2026-05-11",
                        rationale="recuperation a confirmer",
                    )
                ],
            ),
            validation=PlanPatchValidation(
                status="requires_confirmation",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="move_session",
                        status="requires_confirmation",
                        target_session_id=3,
                    ),
                ),
            ),
        )
        grounding = ReplyGroundingPacket(local_date=date(2026, 5, 10), timezone_name="Europe/Paris")
        uncommitted_calls: list[str] = []

        def fake_uncommitted(reply, context, **_kwargs):
            uncommitted_calls.append(reply)
            if len(uncommitted_calls) == 1:
                return "Je peux déplacer la mobilité à lundi. Tu confirmes ?"
            self.assertIn("calée", reply)
            return "Je peux déplacer la mobilité à lundi. Tu confirmes ?"

        with (
            patch(
                "fitmas.conversation_pipeline.final_reply.compose_final_reply",
                return_value="Mobilité calée lundi, c'est bon pour moi.",
            ),
            patch("fitmas.conversation_pipeline.final_reply.verify_uncommitted_reply", side_effect=fake_uncommitted),
            patch(
                "fitmas.conversation_pipeline.final_reply.verify_factual_reply",
                return_value="Mobilité calée lundi, c'est bon pour moi.",
            ),
        ):
            reply = _build_plan_patch_confirmation_prompt(result, grounding=grounding)

        self.assertEqual(reply, "Je peux déplacer la mobilité à lundi. Tu confirmes ?")
        self.assertEqual(len(uncommitted_calls), 2)

    def test_plan_patch_confirmation_repairs_effective_wording_before_user(self) -> None:
        from fitmas.conversation_pipeline import _build_plan_patch_confirmation_prompt

        result = PlanPatchServiceResult(
            patch=PlanPatch(
                coach_message="Je peux remplacer la natation par du vélo facile.",
                operations=[
                    PlanPatchOperation(
                        operation_type="replace_session",
                        target_session_id=8,
                        new_sport_type="cycling",
                        new_session_type="easy",
                        new_duration_min=35,
                        rationale="douleur epaule quand il nage",
                    )
                ],
            ),
            validation=PlanPatchValidation(
                status="requires_confirmation",
                operation_results=(
                    PlanPatchOperationValidation(
                        operation_type="replace_session",
                        status="requires_confirmation",
                        target_session_id=8,
                    ),
                ),
            ),
        )

        def fake_verify(reply, context, **_kwargs):
            self.assertIn("devient", reply)
            self.assertTrue(context.pending_summary)
            return "Je peux remplacer la natation par du vélo facile pour proteger l'epaule. Tu confirmes ?"

        with (
            patch(
                "fitmas.conversation_pipeline.final_reply.compose_final_reply",
                return_value="Ta séance natation de demain devient un vélo facile de 35 minutes.",
            ),
            patch("fitmas.conversation_pipeline.final_reply.verify_uncommitted_reply", side_effect=fake_verify),
        ):
            reply = _build_plan_patch_confirmation_prompt(result)

        self.assertIn("Je peux remplacer", reply)
        self.assertNotIn("devient", reply)

    def test_week_review_requires_confirmation_counts_as_pending(self) -> None:
        from fitmas.conversation_pipeline import _plan_patch_confirmation_summary, _plan_patch_needs_confirmation

        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=()),
            week_policy_status="requires_confirmation",
            week_review=WeekCoherenceReview(
                status="requires_confirmation",
                sport_quality="fragile",
                confidence=0.8,
                summary="La fin de semaine devient trop dense.",
                findings=(),
                suggested_adjustments=(),
                recommended_policy="confirm_original",
            ),
        )

        self.assertTrue(_plan_patch_needs_confirmation(result))
        self.assertEqual(_plan_patch_confirmation_summary(result), "La fin de semaine devient trop dense.")

    def test_plan_patch_pending_summary_and_reason_hide_internal_terms(self) -> None:
        from fitmas.conversation_pipeline import _plan_patch_confirmation_summary, _plan_patch_pending_reason

        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=()),
            week_policy_status="requires_confirmation",
            week_review=WeekCoherenceReview(
                status="requires_confirmation",
                sport_quality="fragile",
                confidence=0.8,
                summary="Reviewer sportif signale une fragilite sur ce patch avant de commiter. Demande si le user confirme.",
                findings=(),
                suggested_adjustments=(),
                recommended_policy="confirm_original",
            ),
        )

        summary = _plan_patch_confirmation_summary(result)
        reason = _plan_patch_pending_reason(result, fallback_reason="plan_patch_requires_confirmation")

        for text in (summary, reason):
            normalized = text.lower()
            self.assertIn("confirm", normalized)
            self.assertNotIn("reviewer", normalized)
            self.assertNotIn("patch", normalized)
            self.assertNotIn("commiter", normalized)
            self.assertNotIn("user", normalized)

    def test_confirmation_reply_clarification_detector_handles_preciser_which_sessions(self) -> None:
        from fitmas.conversation_pipeline import _plan_patch_confirmation_reply_requests_clarification

        replies = [
            "Tu peux me preciser lesquelles exactement tu veux intervertir ?",
            "Avant de confirmer : tu pensais a quel sport pour cette seance longue ?",
            "Je te confirme une fois que tu m'as dit laquelle tu veux bouger en premier.",
            "Tu peux me dire si tu visais la sortie longue de jeudi ou celle de samedi ?",
            "Plusieurs seances en ligne pourraient coller a ta demande.",
        ]

        for reply in replies:
            self.assertTrue(_plan_patch_confirmation_reply_requests_clarification(reply))

        self.assertFalse(_plan_patch_confirmation_reply_requests_clarification("Tu confirmes ce changement ?"))

    def test_week_review_block_surfaces_sport_reason(self) -> None:
        result = PlanPatchServiceResult(
            validation=PlanPatchValidation(status="valid", operation_results=()),
            week_policy_status="blocked",
            week_review=WeekCoherenceReview(
                status="blocked",
                sport_quality="poor",
                confidence=0.82,
                summary="La seance cle est perdue.",
                findings=(
                    WeekCoherenceFinding(
                        code="key_session_lost",
                        severity="blocked",
                        detail="La seance cle disparait de la semaine.",
                    ),
                ),
                suggested_adjustments=(),
                recommended_policy="block_original",
            ),
        )

        with patch("fitmas.conversation_pipeline.final_reply.compose_final_reply", return_value=None):
            reply = _blocked_plan_patch_reply(result)

        self.assertIn("seance cle disparait", reply.lower())

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
