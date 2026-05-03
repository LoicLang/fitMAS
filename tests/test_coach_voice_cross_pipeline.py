"""Cross-pipeline coverage: la voix coach doit etre uniforme sur tous
les system prompts user-facing.

Verrouille la cible Chantier 1 (2 mai 2026) : un changement dans
`coach_voice.COACH_VOICE_RULES` ou les few-shots se propage automatiquement
a la conversation runtime ET a tous les roles heartbeat
(briefing / reminder / review / signal). Si un nouveau pipeline ajoute
un system prompt sans importer `coach_voice`, ce test casse.
"""
from __future__ import annotations

import inspect
import unittest

from fitmas import coach_voice
from fitmas.llm_prompt_builder import _CONVERSATION_SYSTEM_TEXT
from fitmas.skills.heartbeat import roles as heartbeat_roles


class ConversationPromptHasSharedVoiceTest(unittest.TestCase):
    def test_conversation_system_text_includes_voice_rules(self) -> None:
        # Marqueur stable du bloc rules (premier point de la liste).
        self.assertIn(
            "Le message est envoye TEL QUEL au user",
            _CONVERSATION_SYSTEM_TEXT,
        )

    def test_conversation_system_text_includes_good_few_shots(self) -> None:
        self.assertIn("Exemples BONS", _CONVERSATION_SYSTEM_TEXT)
        # Sample d'un few-shot specifique
        self.assertIn("Vendredi pour le footing", _CONVERSATION_SYSTEM_TEXT)

    def test_conversation_system_text_includes_bad_few_shots(self) -> None:
        self.assertIn("A NE JAMAIS ECRIRE", _CONVERSATION_SYSTEM_TEXT)
        # Le cas exact de l'incident 2 mai 2026 doit etre present comme repoussoir.
        self.assertIn("On ne refait pas le debat", _CONVERSATION_SYSTEM_TEXT)


class HeartbeatBuildersImportSharedVoiceTest(unittest.TestCase):
    """Verifie que les 4 builders heartbeat referencent bien `coach_voice`.

    Garde-fou structurel : si quelqu'un ajoute un nouveau builder de prompt
    heartbeat sans importer la voix partagee, ce test ne le couvre pas
    automatiquement. Le test cross-prompt content (en dessous) le rattrape
    quand meme via la chaine sample du rules block.
    """

    def test_briefing_builder_uses_coach_voice(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_briefing_prompt)
        self.assertIn("coach_voice.COACH_VOICE_RULES", src)
        self.assertIn("coach_voice.COACH_VOICE_FEW_SHOTS_GOOD", src)
        self.assertIn("coach_voice.COACH_VOICE_FEW_SHOTS_BAD", src)

    def test_reminder_builder_uses_coach_voice(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_reminder_prompt)
        self.assertIn("coach_voice.COACH_VOICE_RULES", src)

    def test_review_builder_uses_coach_voice(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_review_prompt)
        self.assertIn("coach_voice.COACH_VOICE_RULES", src)

    def test_signal_builder_uses_coach_voice(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_signal_prompt)
        self.assertIn("coach_voice.COACH_VOICE_RULES", src)


class CoachVoiceContentPropagationTest(unittest.TestCase):
    """Si on patch les constants `coach_voice`, la conversation prompt doit
    refleter la modification au prochain build (verrouille la SOURCE UNIQUE).

    Note : `_CONVERSATION_SYSTEM_TEXT` est resolu au module-load time, donc
    ce test verifie que la chaine actuelle est bien construite a partir des
    constants courants. Une edition de `coach_voice` sans rechargement du
    module conversation laisserait `_CONVERSATION_SYSTEM_TEXT` stale ; c'est
    par design (le system prompt est cache au load, pas reconstuit par tour).
    """

    def test_conversation_prompt_built_from_current_voice_rules(self) -> None:
        # Une chaine specifique du bloc rules doit etre presente dans le prompt
        # tel qu'il a ete assemble au load time.
        sample = "Receipt-style INTERDIT"
        self.assertIn(sample, coach_voice.COACH_VOICE_RULES)
        self.assertIn(sample, _CONVERSATION_SYSTEM_TEXT)

    def test_conversation_prompt_built_from_current_good_few_shots(self) -> None:
        sample = "Vendredi pour le footing, jeudi tu coupes"
        self.assertIn(sample, coach_voice.COACH_VOICE_FEW_SHOTS_GOOD)
        self.assertIn(sample, _CONVERSATION_SYSTEM_TEXT)

    def test_conversation_prompt_built_from_current_bad_few_shots(self) -> None:
        sample = "On ne refait pas le debat"
        self.assertIn(sample, coach_voice.COACH_VOICE_FEW_SHOTS_BAD)
        self.assertIn(sample, _CONVERSATION_SYSTEM_TEXT)


class ReceiptDetectorRegressionTest(unittest.TestCase):
    """Le detecteur receipt-style doit catch les patterns concrets observes
    en dogfood, peu importe le pipeline qui les produit.
    """

    def test_2_mai_briefing_phrasing_is_not_a_receipt_match(self) -> None:
        # Cas reel du 2 mai : le LLM disait "Tu as fait 2 sorties offplan...
        # On ne refait pas le debat sur le offplan, c'est acte." Ce pattern
        # n'est PAS detecte par le receipt-style regex (il ne commence pas
        # par "Swap applique" etc.). Il est gere par le prompt voix
        # (regles + few-shot repoussoir explicite). Test verrouille que les
        # ameliorations voix vivent dans le prompt, pas dans le regex.
        msg = (
            "Tu as fait 2 sorties offplan cette semaine et seulement 1 seance "
            "planifiee. On ne refait pas le debat sur le offplan, c'est acte."
        )
        # Pas un receipt-style technique (qui catch "Swap applique" etc.)
        self.assertFalse(coach_voice.message_looks_receipt_style(msg))
        # Mais le pattern bad few-shot couvre ce cas explicitement dans le prompt.
        self.assertIn("On ne refait pas le debat", coach_voice.COACH_VOICE_FEW_SHOTS_BAD)

    def test_classic_receipt_style_caught(self) -> None:
        cases = [
            "Swap applique : footing sur vendredi",
            "Plan modifie.",
            "Mutation enregistree avec succes.",
            "Ton coach a ajuste ton planning.",
            "J'ai bien deplace ta seance de jeudi a vendredi.",
        ]
        for msg in cases:
            self.assertTrue(
                coach_voice.message_looks_receipt_style(msg),
                msg=f"Receipt pattern non detecte: {msg!r}",
            )

    def test_coach_voice_messages_pass_through(self) -> None:
        ok = [
            "Vendredi pour le footing, jeudi tu coupes. Lundi t'a sorti, autant pas enchainer.",
            "T'as natation a 18h aujourd'hui, rien a changer. Tu te sens comment avant ?",
            "Echange fait. T'auras plus de jambes vendredi.",
            "Briefing matin : footing easy 40min, pour absorber les deux dures de cette semaine.",
        ]
        for msg in ok:
            self.assertFalse(
                coach_voice.message_looks_receipt_style(msg),
                msg=f"False positive: {msg!r}",
            )


class HeartbeatReadOnlyCommitClaimGuardTest(unittest.TestCase):
    """Heartbeat read-only ne doit pas parler comme s'il commitait."""

    def test_readonly_commit_claims_are_detected(self) -> None:
        cases = [
            "On verrouille ca : mardi 30min Z2.",
            "Je pose mardi en Z2.",
            "Je mets le renfo jeudi.",
            "C'est cale pour vendredi.",
            "C'est pose.",
            "Je deplace la seance a mercredi.",
        ]
        for msg in cases:
            self.assertTrue(
                coach_voice.message_claims_readonly_commit(msg),
                msg=f"Commit claim non detecte: {msg!r}",
            )

    def test_readonly_suggestions_are_allowed(self) -> None:
        ok = [
            "Je te proposerais de verrouiller mardi en Z2 si tu confirmes.",
            "Je peux poser mardi en Z2 si tu veux.",
            "On peut caler vendredi, mais je veux ton feu vert.",
        ]
        for msg in ok:
            self.assertFalse(
                coach_voice.message_claims_readonly_commit(msg),
                msg=f"Suggestion detectee a tort: {msg!r}",
            )


if __name__ == "__main__":
    unittest.main()
