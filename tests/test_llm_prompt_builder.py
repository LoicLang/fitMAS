from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.llm import make_timeline_summary
from fitmas.llm_prompt_builder import (
    build_conversation_prompt_bundle,
    build_layered_conversation_prompt,
    detect_open_question,
)


class ConversationPromptBuilderTest(unittest.TestCase):
    def test_builds_cached_system_block_and_dynamic_prompt(self) -> None:
        bundle = build_conversation_prompt_bundle(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=2, include_plan_summary=False),
            time_block="Nous sommes mardi 2026-04-01.",
            plan_summary="Legacy plan",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[
                {"role": "user", "text": "Salut"},
                {"role": "agent", "text": "Salut."},
                {"role": "user", "text": "Jeudi c'est quoi deja ?"},
            ],
            coach_context={
                "coach_name": "FitMAS",
                "coach_style": "direct",
                "coach_relationship": "coach",
                "coach_do": "dire vrai",
                "coach_dont": "surjouer",
                "coach_soul": "calme",
                "today_session_id": 12,
            },
            selected_facts=["[constraint] Mardi soir fragile"],
        )

        self.assertEqual(bundle.system[0]["type"], "text")
        self.assertEqual(bundle.system[0]["cache_control"]["type"], "ephemeral")
        self.assertEqual(bundle.system[0]["cache_control"]["ttl"], "1h")
        self.assertIn("Actions possibles", bundle.system[0]["text"])
        self.assertIn("Tu varies l'attaque de tes messages", bundle.system[0]["text"])
        self.assertIn("Tu n'ouvres pas systematiquement par \"Bon\", \"OK\", \"Attends\" ou \"On va etre honnete\"", bundle.system[0]["text"])
        self.assertIn("move_session = deplacer une seule seance vers un slot libre", bundle.system[0]["text"])
        self.assertIn("Je veux le renfo aujourd'hui et la piscine demain", bundle.system[0]["text"])
        self.assertIn("On peut echanger mercredi et jeudi ?", bundle.system[0]["text"])
        self.assertIn("swap_sessions", bundle.system[0]["text"])
        # Sport coherence rules: swap involving a recovery is allowed
        # (the recovery migrates), destructive mutations on protected
        # recovery stay forbidden, and the LLM must flag when moving a
        # hard session should drag its recovery along.
        self.assertIn("recuperation (flexible ou protegee) est autorise", bundle.system[0]["text"])
        self.assertIn("satellite de la seance dure", bundle.system[0]["text"])
        self.assertIn("`replace_session` / `update_session` / `lighten_day` sur un `slot=protected_recovery`", bundle.system[0]["text"])
        self.assertIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertIn("Tempo", bundle.prompt)
        self.assertNotIn("Actions possibles", bundle.prompt)
        self.assertEqual(bundle.history_messages_used, 2)

    def test_layered_builder_splits_system_layers_and_keeps_profile(self) -> None:
        bundle = build_layered_conversation_prompt(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=2, include_plan_summary=False),
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km. Mardi fragile.",
            plan_summary="Legacy plan",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[
                {"role": "user", "text": "Salut"},
                {"role": "agent", "text": "Salut."},
                {"role": "user", "text": "Jeudi c'est quoi deja ?"},
            ],
            coach_context={
                "coach_name": "FitMAS",
                "coach_style": "direct",
                "coach_relationship": "coach",
                "coach_do": "dire vrai",
                "coach_dont": "surjouer",
                "coach_soul": "calme",
                "today_session_id": 12,
            },
            selected_facts=["[constraint] Mardi soir fragile"],
        )

        self.assertGreater(len(bundle.system), 1)
        self.assertIn("Actions possibles", bundle.system[0]["text"])
        self.assertIn("Tu varies l'attaque de tes messages", bundle.system[0]["text"])
        self.assertTrue(any("Profil resume" in part["text"] for part in bundle.system))
        self.assertTrue(any("Calendrier date reel" in part["text"] for part in bundle.system))
        self.assertIn("Source de vérité planning conversationnelle", bundle.prompt)
        self.assertTrue(bundle.prompt.endswith("Nouveau message de l'utilisateur:\nJeudi c'est quoi deja ?"))
        self.assertEqual(bundle.history_messages_used, 2)

    def test_live_prompt_builders_ignore_legacy_plan_anchor_even_if_requested(self) -> None:
        policy = ConversationPromptPolicy(name="forced_legacy", history_limit=2, include_plan_summary=True)

        classic = build_conversation_prompt_bundle(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=policy,
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy plan should never leak.",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )
        layered = build_layered_conversation_prompt(
            user_text="Jeudi c'est quoi deja ?",
            prompt_policy=policy,
            time_block="Nous sommes mardi 2026-04-01.",
            profile_summary="Objectif 10 km.",
            plan_summary="Legacy plan should never leak.",
            timeline_summary="- id=12 | date=2026-04-03 | [running] Tempo",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: demain = 2026-04-02.",
            activity_claim_summary="Claim: aucun.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )

        classic_system = "\n".join(part["text"] for part in classic.system)
        layered_system = "\n".join(part["text"] for part in layered.system)
        self.assertNotIn("Repere legacy semaine courante", classic.prompt)
        self.assertNotIn("Repere legacy semaine courante", classic_system)
        self.assertNotIn("Legacy plan should never leak.", classic.prompt)
        self.assertNotIn("Legacy plan should never leak.", classic_system)
        self.assertNotIn("Repere legacy semaine courante", layered.prompt)
        self.assertNotIn("Repere legacy semaine courante", layered_system)
        self.assertNotIn("Legacy plan should never leak.", layered.prompt)
        self.assertNotIn("Legacy plan should never leak.", layered_system)

    def test_timeline_summary_marks_training_and_flexible_targets(self) -> None:
        summary = make_timeline_summary(
            [
                SimpleNamespace(
                    id=23,
                    scheduled_date="2026-04-14",
                    day="tuesday",
                    sport_type="strength",
                    session_type="general",
                    session_title="Renfo general",
                    session_goal="Socle",
                    completion_status="planned",
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=26,
                    scheduled_date="2026-04-17",
                    day="friday",
                    sport_type="rest",
                    session_type="rest",
                    session_title="Journee flexible",
                    session_goal="Repos",
                    completion_status="planned",
                    flexibility="flexible",
                ),
            ]
        )

        self.assertIn("id=23 | date=2026-04-14 | day=tuesday | slot=training", summary)
        self.assertIn("swappable=true", summary)
        self.assertIn("movable_target=false", summary)
        self.assertIn("id=26 | date=2026-04-17 | day=friday | slot=free_flexible", summary)
        self.assertIn("movable_target=true", summary)
        self.assertIn("can_swap_with_training=true", summary)

    def test_system_prompt_explains_flexible_recovery_swaps(self) -> None:
        bundle = build_conversation_prompt_bundle(
            user_text="Swap la piscine avec vendredi",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=0, include_plan_summary=False),
            time_block="Nous sommes mercredi 2026-04-15.",
            plan_summary="Legacy plan",
            timeline_summary="- id=12 | date=2026-04-15 | slot=training | swappable=true",
            execution_summary="Execution: planned_pending.",
            temporal_summary="Repere temporel: aujourd'hui = 2026-04-15.",
            activity_claim_summary="Claim: non realisation swimming 2026-04-15.",
            signal_summary="Signal: aucun.",
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )

        system_text = "\n".join(part["text"] for part in bundle.system)
        self.assertIn("free_flexible", system_text)
        self.assertIn("la recuperation migre", system_text)


class CoachPostureTest(unittest.TestCase):
    """Chantier 3: posture rule must be in the conversation system prompt so
    the LLM stops asking 'tu veux que je...?' when it could decide itself."""

    def test_system_prompt_contains_decide_and_defend_posture(self) -> None:
        bundle = build_conversation_prompt_bundle(
            user_text="ok",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=0, include_plan_summary=False),
            time_block="Nous sommes mardi.",
            plan_summary="",
            timeline_summary=None,
            execution_summary=None,
            temporal_summary=None,
            activity_claim_summary=None,
            signal_summary=None,
            conversation_history=None,
            coach_context=None,
            selected_facts=[],
        )
        system_text = bundle.system[0]["text"]

        self.assertIn("Posture coach", system_text)
        self.assertIn("Tu DECIDES", system_text)
        self.assertIn("Tu defends ton choix", system_text)
        self.assertIn("Continuation de fil", system_text)
        # The posture must explicitly reject the menu-of-options pattern.
        self.assertIn("Tu ne renvoies pas la balle", system_text)
        self.assertIn("Imprevu", system_text)
        self.assertIn("utilise `propose_replan`", system_text)
        self.assertIn("ne repropose pas un menu running/renfo", system_text)
        self.assertIn("autorisation d'ajuster", system_text)
        self.assertIn("\"demain soir\"", system_text)
        self.assertIn("ne parle jamais comme si plusieurs autres seances etaient deja annulees", system_text)


class OpenQuestionDetectionTest(unittest.TestCase):
    def test_returns_none_when_no_question_mark(self) -> None:
        self.assertIsNone(detect_open_question("Tres bien, on y va."))

    def test_returns_none_for_empty_or_missing(self) -> None:
        self.assertIsNone(detect_open_question(""))
        self.assertIsNone(detect_open_question(None))

    def test_returns_last_question_sentence(self) -> None:
        text = "On a 3 seances. Tu preferes deplacer la natation ou le footing ?"
        self.assertEqual(
            detect_open_question(text),
            "Tu preferes deplacer la natation ou le footing ?",
        )

    def test_ignores_pure_confirmation_tags(self) -> None:
        # "ok ?" / "tu confirmes ?" are administrative pings, not open questions
        self.assertIsNone(detect_open_question("Je decale au jeudi. Ok ?"))
        self.assertIsNone(detect_open_question("On part la-dessus, tu confirmes ?"))

    def test_returns_question_when_only_question_in_text(self) -> None:
        self.assertEqual(
            detect_open_question("Qu'est-ce qui s'est passe mardi ?"),
            "Qu'est-ce qui s'est passe mardi ?",
        )


class OpenQuestionMarkerInjectionTest(unittest.TestCase):
    """Chantier 3: when the previous coach turn ended on an open question, the
    next prompt must surface it so the coach doesn't drop the thread."""

    def _build(self, *, history, layered: bool):
        kwargs = dict(
            user_text="Imprevu, j'ai pas pu",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=4, include_plan_summary=False),
            time_block="Nous sommes mardi.",
            timeline_summary=None,
            execution_summary=None,
            temporal_summary=None,
            activity_claim_summary=None,
            signal_summary=None,
            conversation_history=history,
            coach_context=None,
            selected_facts=[],
        )
        if layered:
            return build_layered_conversation_prompt(**kwargs)
        kwargs["plan_summary"] = ""
        return build_conversation_prompt_bundle(**kwargs)

    def test_classic_builder_injects_open_question_marker(self) -> None:
        history = [
            {"role": "user", "text": "Mardi c'est mort"},
            {"role": "agent", "text": "Compris. Tu veux qu'on garde la natation jeudi a la place ?"},
            {"role": "user", "text": "Imprevu, j'ai pas pu"},
        ]
        bundle = self._build(history=history, layered=False)
        self.assertIn("Question ouverte du tour precedent", bundle.prompt)
        self.assertIn(
            "Tu veux qu'on garde la natation jeudi a la place ?",
            bundle.prompt,
        )

    def test_layered_builder_injects_open_question_marker(self) -> None:
        history = [
            {"role": "user", "text": "Mardi c'est mort"},
            {"role": "agent", "text": "Compris. Qu'est-ce qui s'est passe ?"},
            {"role": "user", "text": "Imprevu, j'ai pas pu"},
        ]
        bundle = self._build(history=history, layered=True)
        self.assertIn("Question ouverte du tour precedent", bundle.prompt)
        self.assertIn("Qu'est-ce qui s'est passe ?", bundle.prompt)

    def test_no_marker_when_previous_coach_turn_was_statement(self) -> None:
        history = [
            {"role": "agent", "text": "Je decale au jeudi."},
            {"role": "user", "text": "Imprevu, j'ai pas pu"},
        ]
        bundle = self._build(history=history, layered=False)
        self.assertNotIn("Question ouverte du tour precedent", bundle.prompt)

    def test_no_marker_when_previous_coach_turn_was_confirmation_only(self) -> None:
        history = [
            {"role": "agent", "text": "Je decale au jeudi. Ok ?"},
            {"role": "user", "text": "Imprevu, j'ai pas pu"},
        ]
        bundle = self._build(history=history, layered=False)
        self.assertNotIn("Question ouverte du tour precedent", bundle.prompt)


class UnresolvedExecutionFollowupInjectionTest(unittest.TestCase):
    """Chantier 3bis: when the pipeline detects an unresolved execution
    clarification it surfaces the question as soft prompt context (not a
    canned reply). The LLM arbitrates whether to ask, integrate or move on."""

    _BLOCK = (
        "Suivi execution non resolu (a toi de juger : creuser, integrer ou ignorer ce tour) :\n"
        "- Hier (2026-04-20) seance prevue id=42 — question candidate : "
        "\"Je ne vois pas de trace nette de ta course hier. Tu l'as faite ou pas ?\"\n"
        "- Pourquoi ca importe : ca change la lecture des seances cle recentes\n"
        "- Si le user vient de te repondre la-dessus (meme indirectement), integre sans reposer la question. "
        "Si tu l'as deja posee dans le tour precedent, ne la repose pas — tranche avec ton hypothese."
    )

    def _build(self, *, layered: bool, followup: str | None):
        kwargs = dict(
            user_text="Tu me conseilles quoi aujourd'hui ?",
            prompt_policy=ConversationPromptPolicy(name="test", history_limit=4, include_plan_summary=False),
            time_block="Nous sommes mardi 2026-04-21.",
            timeline_summary=None,
            execution_summary=None,
            temporal_summary=None,
            activity_claim_summary=None,
            signal_summary=None,
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
            unresolved_execution_followup=followup,
        )
        if layered:
            return build_layered_conversation_prompt(**kwargs)
        kwargs["plan_summary"] = ""
        return build_conversation_prompt_bundle(**kwargs)

    def test_classic_builder_injects_followup_block(self) -> None:
        bundle = self._build(layered=False, followup=self._BLOCK)
        self.assertIn("Suivi execution non resolu", bundle.prompt)
        self.assertIn("Tu l'as faite ou pas", bundle.prompt)
        self.assertIn("a toi de juger", bundle.prompt)

    def test_layered_builder_injects_followup_block(self) -> None:
        bundle = self._build(layered=True, followup=self._BLOCK)
        self.assertIn("Suivi execution non resolu", bundle.prompt)
        self.assertIn("Tu l'as faite ou pas", bundle.prompt)

    def test_no_block_when_followup_is_none(self) -> None:
        bundle = self._build(layered=False, followup=None)
        self.assertNotIn("Suivi execution non resolu", bundle.prompt)


if __name__ == "__main__":
    unittest.main()
