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

    def test_parse_coach_decision_rejects_unknown_memory_action(self) -> None:
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

        self.assertIsNone(decision)

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


if __name__ == "__main__":
    unittest.main()
