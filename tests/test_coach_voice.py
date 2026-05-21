"""Module `coach_voice` — voix coach unifiee partagee tous pipelines.

Source unique de :
- regles voix (texte injecte dans system prompts)
- few-shots BONS / MAUVAIS
- detecteur receipt-style (log-only)
- guard voix (hard, vouvoiement / 3e personne)

Voir docs/SOUL.md section "Voix unifiee partagee — Chantier 1".
"""
from __future__ import annotations

import unittest

from fitmas.coach_voice import (
    COACH_VOICE_FEW_SHOTS_BAD,
    COACH_VOICE_FEW_SHOTS_GOOD,
    COACH_VOICE_RULES,
    RECEIPT_PATTERNS,
    message_has_user_facing_internal_jargon,
    message_looks_receipt_style,
    message_violates_coach_voice,
    normalize_for_voice_guard,
)


class CoachVoiceContentTest(unittest.TestCase):
    def test_rules_block_includes_receipt_ban(self) -> None:
        self.assertIn("Receipt-style INTERDIT", COACH_VOICE_RULES)
        self.assertIn("Swap applique", COACH_VOICE_RULES)
        self.assertIn("Plan modifie", COACH_VOICE_RULES)

    def test_rules_block_includes_anti_recitation(self) -> None:
        self.assertIn("recitation des chiffres bruts", COACH_VOICE_RULES)
        self.assertIn("on ne refait pas le debat", COACH_VOICE_RULES)

    def test_rules_block_includes_anti_cliche(self) -> None:
        self.assertIn("Bravo continue comme ca", COACH_VOICE_RULES)
        self.assertIn("oublie la culpabilite", COACH_VOICE_RULES)

    def test_rules_block_includes_offplan_recognition(self) -> None:
        self.assertIn("offplan", COACH_VOICE_RULES.lower())
        self.assertIn("zero realisees", COACH_VOICE_RULES)

    def test_few_shots_good_present(self) -> None:
        self.assertIn("Exemples BONS", COACH_VOICE_FEW_SHOTS_GOOD)
        self.assertIn("Vendredi pour le footing", COACH_VOICE_FEW_SHOTS_GOOD)
        self.assertIn("briefing matin", COACH_VOICE_FEW_SHOTS_GOOD.lower())

    def test_few_shots_bad_present(self) -> None:
        self.assertIn("A NE JAMAIS ECRIRE", COACH_VOICE_FEW_SHOTS_BAD)
        self.assertIn("Swap applique", COACH_VOICE_FEW_SHOTS_BAD)
        self.assertIn("Le coach a ajuste", COACH_VOICE_FEW_SHOTS_BAD)
        # Le cas exact de l'incident 2 mai 2026 doit servir d'exemple-repoussoir.
        self.assertIn("On ne refait pas le debat", COACH_VOICE_FEW_SHOTS_BAD)


class ReceiptStyleDetectorTest(unittest.TestCase):
    def test_detects_swap_applique(self) -> None:
        self.assertTrue(message_looks_receipt_style("Swap applique : footing sur vendredi"))

    def test_detects_plan_modifie(self) -> None:
        self.assertTrue(message_looks_receipt_style("Plan modifie."))

    def test_detects_mutation_enregistree(self) -> None:
        self.assertTrue(message_looks_receipt_style("Mutation enregistree avec succes."))

    def test_detects_operation_effectuee(self) -> None:
        self.assertTrue(message_looks_receipt_style("Operation effectuee."))

    def test_detects_jai_bien_deplace(self) -> None:
        self.assertTrue(message_looks_receipt_style("J'ai bien deplace ta seance."))
        self.assertTrue(message_looks_receipt_style("J ai bien echange tes seances."))

    def test_detects_ton_coach_a_ajuste(self) -> None:
        self.assertTrue(message_looks_receipt_style("Ton coach a ajuste ton planning."))

    def test_does_not_flag_coach_voice_messages(self) -> None:
        good = [
            "Vendredi pour le footing, jeudi tu coupes.",
            "Le tempo glisse a samedi. Vendredi tu voyages, ca tient pas.",
            "Echange fait. T'auras plus de jambes vendredi.",
            "Tu te sens comment avant la seance ?",
            "On bascule le fractionne en footing easy.",
        ]
        for msg in good:
            self.assertFalse(
                message_looks_receipt_style(msg),
                msg=f"False positive on coach voice: {msg!r}",
            )

    def test_empty_message_is_false(self) -> None:
        self.assertFalse(message_looks_receipt_style(""))
        self.assertFalse(message_looks_receipt_style("   "))

    def test_receipt_patterns_count_stable(self) -> None:
        # Si quelqu'un retire un pattern par accident, ce test casse.
        self.assertEqual(len(RECEIPT_PATTERNS), 6)


class CoachVoiceHardGuardTest(unittest.TestCase):
    def test_detects_vouvoiement(self) -> None:
        self.assertTrue(message_violates_coach_voice("Vos seances de cette semaine"))
        self.assertTrue(message_violates_coach_voice("votre planning a change"))

    def test_detects_third_person_self_reference(self) -> None:
        self.assertTrue(message_violates_coach_voice("Le coach a ajuste ton planning."))
        self.assertTrue(message_violates_coach_voice("Le coach te dit que..."))
        self.assertTrue(message_violates_coach_voice("Le coach vous propose..."))

    def test_detects_analysis_summary_leak(self) -> None:
        self.assertTrue(message_violates_coach_voice("User reports lifting 100 kg and asks what to do next."))
        self.assertTrue(message_violates_coach_voice("User expresses a preference for running in the morning."))
        self.assertTrue(message_violates_coach_voice("Athlete reports running for 30 minutes today."))
        self.assertTrue(message_violates_coach_voice("L'utilisateur indique qu'il prefere courir le matin."))

    def test_does_not_flag_correct_voice(self) -> None:
        ok = [
            "Vendredi pour le footing, jeudi tu coupes.",
            "Tu te sens comment ?",
            "On bascule sur easy.",
        ]
        for msg in ok:
            self.assertFalse(message_violates_coach_voice(msg), msg=f"False positive: {msg!r}")

    def test_empty_message_is_false(self) -> None:
        self.assertFalse(message_violates_coach_voice(""))


class InternalJargonGuardTest(unittest.TestCase):
    def test_detects_observed_internal_leaks(self) -> None:
        self.assertTrue(message_has_user_facing_internal_jargon("Fallback sportif: semaine allegee."))
        self.assertTrue(message_has_user_facing_internal_jargon("Le reviewer demande confirmation."))
        self.assertTrue(message_has_user_facing_internal_jargon("Deux sorties offplan cette semaine."))
        self.assertTrue(message_has_user_facing_internal_jargon("Hello. Voici la reponse pour l'utilisateur."))
        self.assertTrue(message_has_user_facing_internal_jargon('Content : "Ça fait plaisir à entendre."'))
        self.assertTrue(message_has_user_facing_internal_jargon("Je valide avec toi avant de commiter."))
        self.assertTrue(message_has_user_facing_internal_jargon("Le validateur detecte une fragilite."))
        self.assertTrue(message_has_user_facing_internal_jargon("Demande si le user confirme."))
        self.assertTrue(message_has_user_facing_internal_jargon("swap_sessions touche une seance cle."))
        self.assertTrue(message_has_user_facing_internal_jargon("Candidate backend, pas une reponse finale."))
        self.assertTrue(message_has_user_facing_internal_jargon("Candidate possible, confirmation recommandee."))

    def test_does_not_flag_human_equivalents(self) -> None:
        ok = [
            "Semaine allegee par prudence.",
            "Deux sorties hors planning cette semaine.",
            "Je te propose de confirmer ce changement.",
            "Je prefere valider avec toi avant d'appliquer.",
        ]
        for msg in ok:
            self.assertFalse(message_has_user_facing_internal_jargon(msg), msg=f"False positive: {msg!r}")


class NormalizeForVoiceGuardTest(unittest.TestCase):
    def test_strips_accents(self) -> None:
        self.assertEqual(normalize_for_voice_guard("éàçü"), "eacu")

    def test_lowercases(self) -> None:
        self.assertIn("vendredi", normalize_for_voice_guard("VENDREDI Pour Le Footing"))

    def test_replaces_apostrophes(self) -> None:
        # Apostrophe convertie en espace pour permettre les regex `j ai` style
        self.assertIn("j ai", normalize_for_voice_guard("J'ai fait"))

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_for_voice_guard("  multi   espaces   "), "multi espaces")


if __name__ == "__main__":
    unittest.main()
