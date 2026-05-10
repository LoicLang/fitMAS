from __future__ import annotations

import unittest

import fitmas.llm as llm


class CoachDecisionActionsTest(unittest.TestCase):
    def test_parse_coach_decision_accepts_memory_execution_and_pending_resolution(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "execution manquee signalee sans mutation planning immediate",
                "fitmas_message": "Compris. Hier n'est pas fait; je garde le plan lisible avant de bouger quoi que ce soit.",
                "memory_actions": [
                    {
                        "type": "record_health_signal",
                        "health_signal": "fatigue liee a un imprevu travail",
                        "body_area": None,
                        "severity": "unknown",
                        "status": "new",
                        "confidence": 0.72,
                        "evidence": "pas eu le temps hier, imprevu au travail",
                    },
                    {
                        "type": "record_availability",
                        "window_text": "hier",
                        "availability": "unavailable",
                        "starts_on": "2026-04-29",
                        "ends_on": "2026-04-29",
                        "confidence": 0.86,
                        "evidence": "pas eu le temps hier",
                    },
                    {
                        "type": "record_preference",
                        "preference": "prefere les reponses directes sans relance inutile",
                        "polarity": "prefer",
                        "scope": "conversation",
                        "confidence": 0.7,
                        "evidence": "je te demande rien",
                    },
                ],
                "execution_actions": [
                    {
                        "type": "record_execution_update",
                        "target_ref": "seance renfo d'hier",
                        "status": "not_completed",
                        "completed": False,
                        "confidence": 0.94,
                        "evidence": "J'ai pas eu le temps hier malheureusement",
                    }
                ],
                "pending_resolution": {
                    "type": "ignore",
                    "reason": "le message ne repond pas a une confirmation pending",
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(len(decision.memory_actions), 3)
        self.assertEqual(decision.memory_actions[0].type, "record_health_signal")
        self.assertEqual(decision.memory_actions[1].type, "record_availability")
        self.assertEqual(decision.memory_actions[2].type, "record_preference")
        self.assertEqual(len(decision.execution_actions), 1)
        self.assertEqual(decision.execution_actions[0].type, "record_execution_update")
        self.assertEqual(decision.execution_actions[0].completed, False)
        self.assertIsNotNone(decision.pending_resolution)
        assert decision.pending_resolution is not None
        self.assertEqual(decision.pending_resolution.type, "ignore")

    def test_parse_coach_decision_drops_unknown_memory_action_instead_of_failing_turn(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "action memoire inconnue",
                "fitmas_message": "Je garde ca en tete.",
                "memory_actions": [
                    {
                        "type": "record_random_note",
                        "note": "hors contrat",
                    }
                ],
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.memory_actions, ())

    def test_parse_coach_decision_rejects_modify_pending_without_payload(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "modify pending incomplet",
                "fitmas_message": "Je reprends le changement en attente.",
                "pending_resolution": {
                    "type": "modify_pending",
                    "reason": "manque les modifications demandees",
                },
            }
        )

        self.assertIsNone(decision)

    def test_parse_coach_decision_accepts_modify_pending_without_reason_when_changes_present(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "le user modifie une confirmation en attente",
                "fitmas_message": "Je reprends la proposition avec ce changement, sans appliquer l'ancienne.",
                "pending_resolution": {
                    "type": "modify_pending",
                    "requested_changes": "placer l'alternative vendredi",
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNotNone(decision.pending_resolution)
        assert decision.pending_resolution is not None
        self.assertEqual(decision.pending_resolution.type, "modify_pending")
        self.assertEqual(decision.pending_resolution.requested_changes, "placer l'alternative vendredi")

    def test_parse_coach_decision_accepts_selected_pending_choice_candidate(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "le user choisit une option pending_choice",
                "fitmas_message": "Je prends l'option vendredi.",
                "pending_resolution": {
                    "type": "accept_pending",
                    "selected_candidate_id": "llm_candidate_2",
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNotNone(decision.pending_resolution)
        assert decision.pending_resolution is not None
        self.assertEqual(decision.pending_resolution.type, "accept_pending")
        self.assertEqual(decision.pending_resolution.selected_candidate_id, "llm_candidate_2")

    def test_parse_coach_decision_drops_extra_pending_resolution_fields(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "le user confirme une proposition en attente",
                "fitmas_message": "Je prends cette option.",
                "pending_resolution": {
                    "type": "accept_pending",
                    "selected_candidate_id": "llm_candidate_2",
                    "payload": {"noise": "provider extra"},
                    "id": "provider-extra-id",
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNotNone(decision.pending_resolution)
        assert decision.pending_resolution is not None
        self.assertEqual(decision.pending_resolution.type, "accept_pending")
        self.assertEqual(decision.pending_resolution.selected_candidate_id, "llm_candidate_2")

    def test_parse_coach_decision_drops_malformed_pending_resolution_without_failing_turn(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "reponse courte sans resolution exploitable",
                "fitmas_message": "Je reste sur l'option en attente, sans appliquer.",
                "pending_resolution": {
                    "payload": {"decision": "accept"},
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNone(decision.pending_resolution)

    def test_parse_invalid_confirmation_action_is_rejected_for_repair(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "fatigue signalee, adaptation possible mais action invalide",
                "fitmas_message": "Je peux alleger demain si tu veux, mais je ne touche pas au plan sans action claire.",
                "mutation_decision": {
                    "mutation_type": "",
                    "rationale": "fatigue signalee",
                    "fitmas_message": "J'allege demain.",
                },
            }
        )

        self.assertIsNone(decision)

    def test_parse_coach_decision_rejects_missed_yesterday_reply_without_execution_action(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "no_change",
                "rationale": "hier renfo manque, aujourd'hui footing Z2 inchange",
                "fitmas_message": "Vu pour le renfo d'hier, on passe a autre chose. Ce matin, footing Z2 28 min.",
                "execution_actions": [],
            }
        )

        self.assertIsNone(decision)

    def test_parse_requires_confirmation_without_reason_derives_reason_from_rationale(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "deplacement sensible d'une seance cle",
                "fitmas_message": "Je peux le faire, mais je veux confirmation avant de toucher a cette seance.",
                "plan_patch": {
                    "coach_message": "Je peux deplacer la seance cle.",
                    "operations": [
                        {
                            "operation_type": "move_session",
                            "target_session_id": 42,
                            "target_date": "2026-05-12",
                            "rationale": "creneau demande par l'utilisateur",
                        }
                    ],
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.response_type, "requires_confirmation")
        self.assertEqual(decision.confirmation_reason, "deplacement sensible d'une seance cle")
        self.assertIsNotNone(decision.plan_patch)

    def test_parse_requires_confirmation_unwraps_tool_patch_payload(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "adaptation sensible issue d'un draft tool",
                "fitmas_message": "Je peux remplacer la séance, mais je veux confirmation avant de toucher au plan.",
                "confirmation_reason": "remplacement sensible",
                "plan_patch": {
                    "patch": {
                        "coach_message": "Je peux remplacer la natation par un footing doux.",
                        "confirmation_reason": "douleur epaule sur natation",
                        "operations": [
                            {
                                "operation_type": "replace_session",
                                "target_session_id": 42,
                                "new_sport_type": "running",
                                "new_session_type": "easy",
                                "new_duration_min": 30,
                                "new_intensity": "easy",
                                "rationale": "eviter la nage avec epaule douloureuse",
                            }
                        ],
                    },
                    "validation": {"status": "requires_confirmation"},
                    "next_step": "return_requires_confirmation",
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.response_type, "requires_confirmation")
        self.assertIsNotNone(decision.plan_patch)
        assert decision.plan_patch is not None
        self.assertEqual(decision.plan_patch.operations[0].target_session_id, 42)

    def test_parse_requires_confirmation_unwraps_patch_inside_mutation_decision(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "adaptation sensible issue d'un draft tool mal range",
                "fitmas_message": "Je peux remplacer la séance, mais je veux confirmation avant de toucher au plan.",
                "confirmation_reason": "remplacement sensible",
                "mutation_decision": {
                    "mutation_type": "plan_patch",
                    "payload": {
                        "patch": {
                            "coach_message": "Je peux remplacer la natation par un footing doux.",
                            "operations": [
                                {
                                    "operation_type": "replace_session",
                                    "target_session_id": 42,
                                    "new_sport_type": "running",
                                    "new_session_type": "easy",
                                    "new_duration_min": 30,
                                    "new_intensity": "easy",
                                    "rationale": "eviter la nage avec epaule douloureuse",
                                }
                            ],
                        }
                    },
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.response_type, "requires_confirmation")
        self.assertIsNone(decision.mutation_decision)
        self.assertIsNotNone(decision.plan_patch)
        assert decision.plan_patch is not None
        self.assertEqual(decision.plan_patch.operations[0].operation_type, "replace_session")

    def test_parse_requires_confirmation_normalizes_patch_aliases(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "adaptation sensible avec patch mal serialise",
                "fitmas_message": "Je peux alléger la séance, mais je veux confirmation avant de toucher au plan.",
                "confirmation_reason": "fatigue signalee",
                "plan_patch": {
                    "operations": {
                        "operation": "replace_session",
                        "session_id": 42,
                        "new_sport_type": "walking",
                        "new_session_type": "recovery",
                        "new_duration_min": 20,
                        "new_intensity": "easy",
                        "rationale": "garder du mouvement sans charger les jambes",
                    }
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNotNone(decision.plan_patch)
        assert decision.plan_patch is not None
        self.assertEqual(decision.plan_patch.coach_message, decision.fitmas_message)
        self.assertEqual(decision.plan_patch.operations[0].operation_type, "replace_session")
        self.assertEqual(decision.plan_patch.operations[0].target_session_id, 42)

    def test_parse_requires_confirmation_extracts_revised_patch_from_review_envelope(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "review propose une version plus prudente",
                "fitmas_message": "Je peux remplacer la natation, mais je veux confirmation avant de toucher au plan.",
                "confirmation_reason": "douleur epaule",
                "plan_patch": {
                    "validation": {"status": "requires_confirmation"},
                    "review": {
                        "revised_patch": {
                            "coach_message": "Je peux remplacer la natation par du vélo facile.",
                            "operations": [
                                {
                                    "operation_type": "replace_session",
                                    "target_session_id": 42,
                                    "new_sport_type": "cycling",
                                    "new_session_type": "easy",
                                    "new_duration_min": 35,
                                    "new_intensity": "easy",
                                    "rationale": "eviter l'epaule douloureuse",
                                }
                            ],
                        }
                    },
                },
            }
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNotNone(decision.plan_patch)
        assert decision.plan_patch is not None
        self.assertEqual(decision.plan_patch.operations[0].new_sport_type, "cycling")

    def test_parse_free_requires_confirmation_is_rejected_for_repair(self) -> None:
        decision = llm.parse_coach_decision_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "hypothese de mutation sans patch structure",
                "fitmas_message": "Je peux bouger la course plus tard si tu confirmes.",
                "confirmation_reason": "option a confirmer",
            }
        )

        self.assertIsNone(decision)

    def test_free_confirmation_repair_downgrades_to_neutral_no_change_artifact(self) -> None:
        repaired = llm._downgrade_free_confirmation_payload(
            {
                "response_type": "requires_confirmation",
                "rationale": "fatigue signalee, adaptation sensible",
                "fitmas_message": "On zappe la seance et on remplace par marche.",
                "confirmation_reason": "adaptation sensible",
            }
        )

        self.assertIsNotNone(repaired)
        assert repaired is not None
        self.assertEqual(repaired["response_type"], "no_change")
        self.assertIsNone(repaired["confirmation_reason"])
        self.assertNotIn("zappe", repaired["fitmas_message"].lower())
        self.assertIn("Signal pris", repaired["fitmas_message"])


if __name__ == "__main__":
    unittest.main()
