"""Cross-pipeline coverage: la voix coach doit rester source unique sur les
prompts qui produisent directement une parole user-facing.

Verrouille la cible Chantier 1 (2 mai 2026) : un changement dans
`coach_voice.COACH_VOICE_RULES` ou les few-shots se propage automatiquement
a la conversation runtime. Depuis le composer terminal heartbeat, les roles
heartbeat ne portent plus la voix complete : ils preparent un brouillon factuel,
puis `final_reply.compose_heartbeat_reply()` applique la voix finale.
"""
from __future__ import annotations

import inspect
import unittest

from fitmas.domain.coaching import coach_voice
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


class HeartbeatBuildersUseDraftContractTest(unittest.TestCase):
    """Les roles heartbeat preparent le fond, pas la voix finale."""

    def test_briefing_builder_uses_draft_contract(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_briefing_prompt)
        self.assertIn("_HEARTBEAT_DRAFT_CONTRACT", src)
        self.assertNotIn("COACH_VOICE_FEW_SHOTS", src)

    def test_reminder_builder_uses_draft_contract(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_reminder_prompt)
        self.assertIn("_HEARTBEAT_DRAFT_CONTRACT", src)
        self.assertNotIn("COACH_VOICE_FEW_SHOTS", src)

    def test_review_builder_uses_draft_contract(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_review_prompt)
        self.assertIn("_HEARTBEAT_DRAFT_CONTRACT", src)
        self.assertNotIn("COACH_VOICE_FEW_SHOTS", src)

    def test_signal_builder_uses_draft_contract(self) -> None:
        src = inspect.getsource(heartbeat_roles.build_signal_prompt)
        self.assertIn("_HEARTBEAT_DRAFT_CONTRACT", src)
        self.assertNotIn("COACH_VOICE_FEW_SHOTS", src)


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


if __name__ == "__main__":
    unittest.main()
