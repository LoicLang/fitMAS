from __future__ import annotations

from fitmas.final_reply import (
    BlockedEvent,
    FinalReplyContext,
    build_post_event_reply_verifier_prompt,
    build_final_reply_prompt,
    close_turn_outage_fallback_reply,
    compose_final_reply,
    compose_close_turn_reply,
    compose_no_change_reply,
    compose_plan_lookup_reply,
    is_valid_close_turn_reply,
    is_valid_final_reply,
    is_valid_plan_lookup_reply,
    outage_fallback_reply,
    verify_post_event_reply,
)


def _blocked_context() -> FinalReplyContext:
    return FinalReplyContext(
        user_text="Mets la seance de mercredi sur jeudi",
        original_llm_reply="Je deplace mercredi a jeudi.",
        blocked_events=(
            BlockedEvent(
                command="move_session",
                reason="same_sport_proximity",
                suggested_fix="choisir une date a plus de 48h",
            ),
        ),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )


def test_prompt_contains_backend_truth_without_authorizing_action_claims() -> None:
    system, prompt = build_final_reply_prompt(_blocked_context())

    assert "same_sport_proximity" in prompt
    assert "choisir une date a plus de 48h" in prompt
    assert "Aucun changement planning n'a ete commit" in prompt
    assert "ne claim pas une action appliquee" in prompt
    assert "Voix coach" in system


def test_validation_rejects_old_backend_templates() -> None:
    ctx = _blocked_context()

    assert is_valid_final_reply("Je n'ai applique aucun changement sur ce tour.", ctx) is False
    assert is_valid_final_reply("Dis-moi explicitement ce que tu veux que je deplace.", ctx) is False
    assert is_valid_final_reply("Mutation enregistree avec succes.", ctx) is False


def test_validation_rejects_action_claim_when_no_commit_allowed() -> None:
    ctx = _blocked_context()

    assert is_valid_final_reply("Je deplace la seance a jeudi.", ctx) is False
    assert is_valid_final_reply("Echange fait. Tu confirmes pour garder ca ?", ctx) is False
    assert is_valid_final_reply("Je peux l'echanger avec vendredi si tu veux.", ctx) is True


def test_validation_rejects_user_facing_internal_jargon() -> None:
    ctx = _blocked_context()

    invalid = [
        "Hello. Voici la reponse pour l'utilisateur.",
        "Fallback sportif: semaine allegee apres review sportive.",
        "Le reviewer demande confirmation sur ce patch.",
        "Deux sorties offplan cette semaine.",
        "Je commit le changement.",
    ]

    for reply in invalid:
        assert is_valid_final_reply(reply, ctx) is False

    assert is_valid_final_reply("Deux sorties hors planning cette semaine.", ctx) is True
    assert is_valid_final_reply("Je te propose de confirmer ce changement.", ctx) is True


def test_compose_final_reply_uses_request_text_and_validates_output() -> None:
    ctx = _blocked_context()

    def fake_request_text(**kwargs):
        assert "same_sport_proximity" in kwargs["prompt"]
        return "Je garde plus de 48h entre deux seances du meme sport."

    reply = compose_final_reply(ctx, request_text_fn=fake_request_text)

    assert reply == "Je garde plus de 48h entre deux seances du meme sport."


def test_compose_final_reply_drops_invalid_output() -> None:
    ctx = _blocked_context()

    def fake_request_text(**kwargs):
        return "Je deplace la seance a jeudi."

    assert compose_final_reply(ctx, request_text_fn=fake_request_text) is None


def test_validation_rejects_confirmation_question_after_committed_event() -> None:
    ctx = FinalReplyContext(
        committed_events=("Tempo deplace a jeudi.",),
        allowed_to_claim_mutation=True,
    )

    assert is_valid_final_reply("Je le glisse a jeudi. Tu confirmes jeudi soir pour le tempo ?", ctx) is False
    assert is_valid_final_reply("Je le glisse a jeudi. Meme stimulus, juste decale.", ctx) is True


def test_outage_fallback_is_short_and_non_technical() -> None:
    fallback = outage_fallback_reply(_blocked_context())

    assert 0 < len(fallback) < 220
    assert "mutation" not in fallback.lower()
    assert "block_reason" not in fallback.lower()
    assert "n'ai applique aucun changement" not in fallback


def test_close_turn_composer_uses_terminal_context() -> None:
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            assert "Dernier message coach visible: Tu veux un point semaine ?" in kwargs["prompt"]
            return '{"verdict":"allow","reason":"fermeture courte"}'
        assert "terminal_close" in kwargs["prompt"]
        assert "Ne relance pas le user" in kwargs["prompt"]
        assert "Dernier message coach: Tu veux un point semaine ?" in kwargs["prompt"]
        return "Carre, on s'arrete la."

    reply = compose_close_turn_reply(
        user_text="Okay chef",
        previous_agent_text="Tu veux un point semaine ?",
        request_text_fn=fake_request_text,
    )

    assert reply == "Carre, on s'arrete la."
    assert verifier_calls == 1


def test_close_turn_composer_retries_before_outage_fallback_phrase() -> None:
    compose_calls = 0
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal compose_calls, verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            return '{"verdict":"allow","reason":"fermeture courte"}'
        compose_calls += 1
        if compose_calls == 1:
            return "Carre, on garde ca."
        assert "Premiere proposition rejetee" in kwargs["prompt"]
        return "Parfait. Tu deroules les 36 minutes tranquille."

    reply = compose_close_turn_reply(
        user_text="Parfait on fait ça",
        previous_agent_text="Aujourd'hui retour en piste : 36 min footing, allure parole.",
        request_text_fn=fake_request_text,
    )

    assert reply == "Parfait. Tu deroules les 36 minutes tranquille."
    assert compose_calls == 2
    assert verifier_calls == 1


def test_close_turn_verifier_repairs_meta_intent_explanations() -> None:
    compose_calls = 0
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal compose_calls, verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            assert 'je prends ca comme' in kwargs["prompt"]
            return (
                '{"verdict":"repair","reason":"meta",'
                '"repaired_reply":"Parfait. Rien a ajouter pour ce tour."}'
            )
        compose_calls += 1
        return '"Okay chef" - je prends ca comme un "on est cale, pas de question".'

    reply = compose_close_turn_reply(
        user_text="Okay chef",
        previous_agent_text="Tu veux un point semaine ?",
        request_text_fn=fake_request_text,
    )

    assert reply == "Parfait. Rien a ajouter pour ce tour."
    assert compose_calls == 1
    assert verifier_calls == 1


def test_close_turn_verifier_repairs_followup_invitations() -> None:
    compose_calls = 0
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal compose_calls, verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            assert "tu me tiens au jus" in kwargs["prompt"]
            return (
                '{"verdict":"repair","reason":"rouvre le fil",'
                '"repaired_reply":"Parfait. Rien a ajouter pour ce tour."}'
            )
        compose_calls += 1
        return "Pas de souci, tu me tiens au jus si tu veux qu'on touche a quelque chose."

    reply = compose_close_turn_reply(
        user_text="Okay chef",
        previous_agent_text="Tu veux un point semaine ?",
        request_text_fn=fake_request_text,
    )

    assert reply == "Parfait. Rien a ajouter pour ce tour."
    assert compose_calls == 1
    assert verifier_calls == 1


def test_close_turn_verifier_repairs_unsupported_plan_facts() -> None:
    compose_calls = 0
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal compose_calls, verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            assert "On reprend mardi avec la poutre" in kwargs["prompt"]
            return (
                '{"verdict":"repair","reason":"fait planning absent du contexte",'
                '"repaired_reply":"Parfait. Rien a ajouter pour ce tour."}'
            )
        compose_calls += 1
        return "Pas de point necessaire. On reprend mardi avec la poutre."

    reply = compose_close_turn_reply(
        user_text="Okay chef",
        previous_agent_text="Tu veux un point semaine ?",
        request_text_fn=fake_request_text,
    )

    assert reply == "Parfait. Rien a ajouter pour ce tour."
    assert compose_calls == 1
    assert verifier_calls == 1


def test_close_turn_verifier_allows_supported_plan_facts() -> None:
    verifier_calls = 0

    def fake_request_text(**kwargs):
        nonlocal verifier_calls
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            verifier_calls += 1
            assert "36 min footing" in kwargs["prompt"]
            return '{"verdict":"allow","reason":"faits repris du dernier coach"}'
        return "Parfait. Tu deroules les 36 minutes tranquille."

    reply = compose_close_turn_reply(
        user_text="Parfait on fait ca",
        previous_agent_text="Aujourd'hui retour en piste : 36 min footing, allure parole.",
        request_text_fn=fake_request_text,
    )

    assert reply == "Parfait. Tu deroules les 36 minutes tranquille."
    assert verifier_calls == 1


def test_close_turn_validation_rejects_questions_and_action_claims() -> None:
    assert is_valid_close_turn_reply("Tu veux que je te fasse un point demain ?") is False
    assert is_valid_close_turn_reply("Je deplace ca a demain.") is False
    assert is_valid_close_turn_reply("Mutation enregistree.") is False
    assert is_valid_close_turn_reply("Carre, on garde ca.") is False


def test_close_turn_outage_fallback_is_terminal() -> None:
    fallback = close_turn_outage_fallback_reply()

    assert is_valid_close_turn_reply(fallback, allow_outage_fallback=True)
    assert "?" not in fallback


def test_no_change_composer_uses_original_reply_as_draft() -> None:
    def fake_request_text(**kwargs):
        assert "no_change" in kwargs["prompt"]
        assert "Brouillon LLM initial: Je te fais le point sans toucher au plan." in kwargs["prompt"]
        assert "Aucun changement planning n'a ete commit" in kwargs["prompt"]
        return "Tu gardes le footing facile ce soir, sans chercher a en rajouter."

    reply = compose_no_change_reply(
        user_text="Je fais quoi ce soir ?",
        original_llm_reply="Je te fais le point sans toucher au plan.",
        request_text_fn=fake_request_text,
    )

    assert reply == "Tu gardes le footing facile ce soir, sans chercher a en rajouter."


def test_no_change_composer_can_include_applied_non_plan_actions() -> None:
    def fake_request_text(**kwargs):
        assert "Renfo 34min notee comme non faite." in kwargs["prompt"]
        assert "Memoire utilisateur mise a jour." in kwargs["prompt"]
        return "Renfo note non fait. Ce soir tu gardes simple."

    reply = compose_no_change_reply(
        user_text="J'ai pas eu le temps hier",
        original_llm_reply="Note pour hier. On garde ce matin simple.",
        execution_actions_applied=("Renfo 34min notee comme non faite.",),
        memory_actions_applied=("Memoire utilisateur mise a jour.",),
        request_text_fn=fake_request_text,
    )

    assert reply == "Renfo note non fait. Ce soir tu gardes simple."


def test_plan_lookup_composer_uses_fact_preservation_context() -> None:
    def fake_request_text(**kwargs):
        assert "plan_lookup" in kwargs["prompt"]
        assert "ne change aucun fait date" in kwargs["prompt"].lower()
        assert "Brouillon LLM initial: Demain: footing 36 min Z2." in kwargs["prompt"]
        return "Demain, footing de 36 min en Z2."

    reply = compose_plan_lookup_reply(
        user_text="J'ai quoi demain ?",
        original_llm_reply="Demain: footing 36 min Z2.",
        request_text_fn=fake_request_text,
    )

    assert reply == "Demain, footing de 36 min en Z2."


def test_plan_lookup_validation_is_shape_only_without_grounding() -> None:
    assert is_valid_plan_lookup_reply(
        "Demain, footing de 40 min en Z2.",
        original_llm_reply="Demain: footing 36 min Z2.",
    ) is True
    assert is_valid_plan_lookup_reply(
        "Demain, footing de 36 min en Z2.",
        original_llm_reply="Demain: footing 36 min Z2.",
    ) is True


def test_plan_lookup_composer_requires_grounding_for_fact_repair() -> None:
    reply = compose_plan_lookup_reply(
        user_text="J'ai quoi demain ?",
        original_llm_reply="Demain: footing 36 min Z2.",
        request_text_fn=lambda **kwargs: "Demain, footing de 40 min en Z2.",
    )

    assert reply == "Demain, footing de 40 min en Z2."


def test_plan_lookup_composer_keeps_original_when_rewrite_reopens_turn() -> None:
    reply = compose_plan_lookup_reply(
        user_text="J'ai quoi demain ?",
        original_llm_reply="Demain: footing 36 min Z2.",
        request_text_fn=lambda **kwargs: "Demain, footing de 36 min en Z2. Tu veux le detail ?",
    )

    assert reply == "Demain: footing 36 min Z2."


def _committed_context() -> FinalReplyContext:
    return FinalReplyContext(
        committed_events=(
            "Mercredi remplace par Journee flexible.",
            "Jeudi remplace par Journee flexible.",
        ),
        allowed_to_claim_mutation=True,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )


def test_post_event_verifier_prompt_contains_only_machine_truth_and_reply() -> None:
    ctx = _committed_context()

    system, prompt = build_post_event_reply_verifier_prompt(
        ctx,
        "J'ai decale le fractionne a jeudi.",
    )

    assert "post-mutation" in system
    assert "Mercredi remplace par Journee flexible" in prompt
    assert "Jeudi remplace par Journee flexible" in prompt
    assert "J'ai decale le fractionne a jeudi" in prompt
    assert "Message user" not in prompt


def test_post_event_verifier_allows_faithful_reply() -> None:
    ctx = _committed_context()

    def fake_request_text(**kwargs):
        assert "Mercredi remplace par Journee flexible" in kwargs["prompt"]
        return '{"verdict":"allow","reason":"la reply suit les events"}'

    reply = verify_post_event_reply(
        "Mercredi et jeudi passent en journees flexibles.",
        ctx,
        request_text_fn=fake_request_text,
    )

    assert reply == "Mercredi et jeudi passent en journees flexibles."


def test_post_event_verifier_repairs_contradictory_reply() -> None:
    ctx = _committed_context()

    def fake_request_text(**kwargs):
        assert "J'ai decale le fractionne a jeudi" in kwargs["prompt"]
        return (
            '{"verdict":"repair","reason":"la reply invente un deplacement",'
            '"repaired_reply":"J ai libere mercredi et jeudi en journees flexibles."}'
        )

    reply = verify_post_event_reply(
        "J'ai decale le fractionne a jeudi.",
        ctx,
        request_text_fn=fake_request_text,
    )

    assert reply == "J ai libere mercredi et jeudi en journees flexibles."


def test_post_event_verifier_falls_back_when_judge_is_invalid() -> None:
    ctx = _committed_context()

    def fake_request_text(**kwargs):
        return "ALLOW"

    assert (
        verify_post_event_reply(
            "J'ai decale le fractionne a jeudi.",
            ctx,
            request_text_fn=fake_request_text,
        )
        is None
    )


def test_post_event_verifier_rejects_invalid_repair() -> None:
    ctx = _committed_context()

    def fake_request_text(**kwargs):
        return '{"verdict":"repair","repaired_reply":"Tu confirmes ?"}'

    assert (
        verify_post_event_reply(
            "J'ai decale le fractionne a jeudi.",
            ctx,
            request_text_fn=fake_request_text,
        )
        is None
    )
