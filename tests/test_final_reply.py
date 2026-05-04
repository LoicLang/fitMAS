from __future__ import annotations

from fitmas.final_reply import (
    BlockedEvent,
    FinalReplyContext,
    build_post_event_reply_verifier_prompt,
    build_final_reply_prompt,
    compose_final_reply,
    is_valid_final_reply,
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
                reason="protected_recovery_target",
                suggested_fix="swap_sessions vers vendredi",
            ),
        ),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )


def test_prompt_contains_backend_truth_without_authorizing_action_claims() -> None:
    system, prompt = build_final_reply_prompt(_blocked_context())

    assert "protected_recovery_target" in prompt
    assert "swap_sessions vers vendredi" in prompt
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
    assert is_valid_final_reply("Je peux l'echanger avec vendredi si tu veux.", ctx) is True


def test_compose_final_reply_uses_request_text_and_validates_output() -> None:
    ctx = _blocked_context()

    def fake_request_text(**kwargs):
        assert "protected_recovery_target" in kwargs["prompt"]
        return "Je ne l'ecrase pas : ce creneau protege ta recup. Je peux plutot echanger avec vendredi."

    reply = compose_final_reply(ctx, request_text_fn=fake_request_text)

    assert reply == "Je ne l'ecrase pas : ce creneau protege ta recup. Je peux plutot echanger avec vendredi."


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
