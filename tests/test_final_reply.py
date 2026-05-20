from __future__ import annotations

from fitmas.final_reply import (
    BlockedEvent,
    FinalReplyContext,
    HeartbeatReplyContext,
    HeartbeatReplyFact,
    build_post_event_reply_verifier_prompt,
    build_heartbeat_reply_prompt,
    build_final_reply_prompt,
    close_turn_outage_fallback_reply,
    compose_heartbeat_reply,
    compose_final_reply,
    compose_close_turn_reply,
    compose_execution_report_reply,
    compose_no_change_reply,
    compose_plan_adaptation_reply,
    compose_plan_lookup_reply,
    is_valid_close_turn_reply,
    is_valid_final_reply,
    is_valid_plan_lookup_reply,
    outage_fallback_reply,
    verify_uncommitted_reply,
    verify_post_event_reply,
)
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


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


def test_validation_rejects_analysis_summary_leak() -> None:
    ctx = _blocked_context()

    assert is_valid_final_reply("User reports lifting 100 kg and asks what to do next.", ctx) is False
    assert is_valid_final_reply("L'utilisateur indique qu'il prefere courir le matin.", ctx) is False


def test_validation_rejects_memory_claim_without_memory_event() -> None:
    ctx = FinalReplyContext(
        user_text="je prefere courir le matin",
        original_llm_reply="Je retiens que tu preferes courir le matin.",
        memory_actions_applied=(),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="no_change",
    )

    assert is_valid_final_reply("Je retiens que tu preferes courir le matin.", ctx) is False
    assert is_valid_final_reply("Courir le matin, ca colle bien quand le planning le permet.", ctx) is True


def test_validation_rejects_execution_registration_talk_without_execution_event() -> None:
    ctx = FinalReplyContext(
        user_text="putain je fais 100kg",
        original_llm_reply="Je ne vois pas de nouvelle seance enregistree.",
        execution_actions_applied=(),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="no_change",
    )

    assert is_valid_final_reply("Je ne vois pas de nouvelle seance enregistree.", ctx) is False
    assert is_valid_final_reply("On traite ca comme un point de repere, pas comme une alerte.", ctx) is True


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
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"ok"}'
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


def test_no_change_composer_uses_uncommitted_verifier_for_action_claims() -> None:
    calls = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return (
                '{"verdict":"repair","reason":"parle comme si annule",'
                '"repaired_reply":"Je l ai note; je verifie la semaine avant de toucher au plan."}'
            )
        return "On laisse tomber le footing de demain."

    reply = compose_no_change_reply(
        user_text="Inondation chez moi, pas de sport aujourd'hui ni demain",
        original_llm_reply="On laisse tomber le footing de demain.",
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Je l ai note; je verifie la semaine avant de toucher au plan."
    assert any("Events commits: aucun changement planning commit." in prompt for prompt in calls)


def test_no_change_composer_can_include_applied_non_plan_actions() -> None:
    def fake_request_text(**kwargs):
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"actions supportees"}'
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


def test_execution_report_composer_repairs_receipt_without_applied_action() -> None:
    calls = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            assert "Execution appliquee:" not in kwargs["prompt"]
            return (
                '{"verdict":"repair","reason":"execution non appliquee",'
                '"repaired_reply":"Je garde ca comme info, sans le noter comme fait tant que la cible reste floue."}'
            )
        assert "execution_report" in kwargs["prompt"]
        return "C'est note comme fait, 30 minutes ajoutees."

    reply = compose_execution_report_reply(
        user_text="J'ai couru aujourd'hui 30 min",
        original_llm_reply="C'est note comme fait.",
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Je garde ca comme info, sans le noter comme fait tant que la cible reste floue."
    assert len(calls) == 2


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


def test_uncommitted_verifier_repairs_pending_action_claim() -> None:
    ctx = FinalReplyContext(
        user_text="J'ai mal a l'epaule quand je nage, ca tire",
        pending_summary="Remplacer la natation par du velo facile demande confirmation.",
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="plan_patch_confirmation",
        extra_facts=(
            "operation#1 | replace_session | target_session_id=8 | new_sport_type=cycling | new_duration_min=35",
        ),
    )

    def fake_request_text(**kwargs):
        assert "Confirmation en attente" in kwargs["prompt"]
        assert "Ta seance natation de demain devient" in kwargs["prompt"]
        return (
            '{"verdict":"repair","reason":"parle comme si applique",'
            '"repaired_reply":"Je peux remplacer la natation par du velo facile pour proteger l epaule. Tu confirmes ?"}'
        )

    reply = verify_uncommitted_reply(
        "Ta seance natation de demain devient un velo facile de 35 minutes.",
        ctx,
        request_text_fn=fake_request_text,
    )

    assert reply == "Je peux remplacer la natation par du velo facile pour proteger l epaule. Tu confirmes ?"


def test_uncommitted_verifier_retries_pending_allow_without_confirmation_question() -> None:
    ctx = FinalReplyContext(
        pending_summary="Allegement du footing a confirmer.",
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="plan_patch_confirmation",
        extra_facts=("operation#1 | replace_session | new_duration_min=25",),
    )
    calls = 0

    def fake_request_text(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"verdict":"allow","reason":"semble proposition"}'
        assert "Verdict precedent invalide" in kwargs["prompt"]
        return (
            '{"verdict":"repair","reason":"confirmation manquante",'
            '"repaired_reply":"Je te propose de raccourcir le footing a 25 minutes faciles. Tu confirmes ?"}'
        )

    reply = verify_uncommitted_reply(
        "Je raccourcis le footing a 25 minutes faciles.",
        ctx,
        request_text_fn=fake_request_text,
    )

    assert reply == "Je te propose de raccourcir le footing a 25 minutes faciles. Tu confirmes ?"
    assert calls == 2


def test_plan_adaptation_pending_reply_uses_uncommitted_verifier() -> None:
    policy = AdaptationPolicyDecision(
        action="pending_confirmation",
        selected_candidate_id="candidate_1",
        candidate_options=(),
        reason="shoulder pain",
        user_facing_reason="L'epaule tire sur la natation.",
        requires_confirmation_reason="Remplacer la natation par du velo facile demande confirmation.",
        risk_level="medium",
    )

    calls = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return (
                '{"verdict":"repair","reason":"pending surclaim",'
                '"repaired_reply":"Je te propose velo facile a la place de la natation, sans forcer l epaule. Tu confirmes ?"}'
            )
        return "Ta seance natation devient un velo facile."

    reply = compose_plan_adaptation_reply(
        policy_decision=policy,
        user_text="J'ai mal a l'epaule quand je nage",
        candidate_summaries=("candidate_1: replace natation -> velo facile",),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Je te propose velo facile a la place de la natation, sans forcer l epaule. Tu confirmes ?"
    assert len(calls) == 2


def test_heartbeat_reply_prompt_hides_internal_fact_categories() -> None:
    context = HeartbeatReplyContext(
        role="briefing",
        capability="read_only",
        temporal=("vendredi 8 mai 2026, 07:30",),
        today_truth=("Footing endurance, 40 min Z2, planned.",),
        week_digest=("planned=2, confirmed=1",),
        active_facts=(
            HeartbeatReplyFact(
                category="health",
                value="Tension tibias tres legere, pas de douleur a la palpation.",
            ),
        ),
        draft="Bonjour. Vendredi — Footing endurance — 40 min Z2.",
        forbidden_claims=("aucun changement planning commit",),
    )

    system, prompt = build_heartbeat_reply_prompt(context)

    assert "compose le message heartbeat final" in system
    assert "Tension tibias tres legere" in prompt
    assert "health" not in prompt
    assert "[health]" not in prompt
    assert "Bonjour. Vendredi" in prompt


def test_compose_heartbeat_reply_uses_context_and_validates_output() -> None:
    context = HeartbeatReplyContext(
        role="briefing",
        capability="read_only",
        temporal=("vendredi 8 mai 2026, 07:30",),
        today_truth=("Footing endurance, 40 min Z2, planned.",),
        active_facts=(
            HeartbeatReplyFact(category="health", value="Tension tibias tres legere."),
        ),
        draft="Bonjour. Vendredi — Footing endurance — 40 min Z2.",
        forbidden_claims=("aucun changement planning commit",),
    )

    def fake_request_text(**kwargs):
        assert "Footing endurance" in kwargs["prompt"]
        assert "Tension tibias tres legere" in kwargs["prompt"]
        assert "health" not in kwargs["prompt"]
        return "Footing easy 40 min en Z2. Tension tibias legere: tu restes souple, sans forcer."

    reply = compose_heartbeat_reply(context, request_text_fn=fake_request_text)

    assert reply == "Footing easy 40 min en Z2. Tension tibias legere: tu restes souple, sans forcer."
