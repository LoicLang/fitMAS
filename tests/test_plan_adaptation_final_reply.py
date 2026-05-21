from __future__ import annotations

from fitmas.llm.reply_backend import compose_plan_adaptation_reply
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


def test_adaptation_commit_reply_is_verified_against_committed_events() -> None:
    calls: list[str] = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"event supporte","repaired_reply":""}'
        return "C'est cale : le footing passe vendredi, sans toucher au reste."

    reply = compose_plan_adaptation_reply(
        policy_decision=_decision(action="commit", selected_candidate_id="cand_1"),
        committed_events=("Footing deplace au vendredi.",),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "C'est cale : le footing passe vendredi, sans toucher au reste."
    assert any("Events commits:" in prompt for prompt in calls)


def test_adaptation_pending_confirmation_rejects_applied_claim() -> None:
    def fake_request_text(**kwargs):
        return "J'ai deplace la seance a vendredi."

    reply = compose_plan_adaptation_reply(
        policy_decision=_decision(
            action="pending_confirmation",
            selected_candidate_id="cand_1",
            requires_confirmation_reason="Possible mais sensible.",
        ),
        request_text_fn=fake_request_text,
    )

    assert reply is None


def test_adaptation_pending_choice_keeps_options_uncommitted() -> None:
    prompts: list[str] = []

    def fake_request_text(**kwargs):
        prompts.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"options non appliquees","repaired_reply":""}'
        return "J'ai deux options propres : vendredi ou alleger demain. Tu choisis ?"

    reply = compose_plan_adaptation_reply(
        policy_decision=_decision(
            action="pending_choice",
            candidate_options=("move_friday", "reduce_tomorrow"),
            requires_confirmation_reason="Deux options sont proches.",
        ),
        candidate_summaries=(
            "move_friday: deplacer la seance a vendredi.",
            "reduce_tomorrow: garder demain mais alleger.",
        ),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "J'ai deux options propres : vendredi ou alleger demain. Tu choisis ?"
    assert "Option candidate: move_friday" in prompts[0]
    assert "Contrainte: presente ces options comme des propositions non appliquees." in prompts[0]


def test_adaptation_block_reply_uses_blocked_context() -> None:
    prompts: list[str] = []

    def fake_request_text(**kwargs):
        prompts.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"blocage sans commit","repaired_reply":""}'
        return "Je ne le fais pas tel quel : aucune option valide ne tient proprement."

    reply = compose_plan_adaptation_reply(
        policy_decision=_decision(action="block", reason="Aucune option valide."),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Je ne le fais pas tel quel : aucune option valide ne tient proprement."
    assert "Evenements bloques:" in prompts[0]
    assert "Aucune option valide." in prompts[0]


def _decision(
    *,
    action: str,
    selected_candidate_id: str | None = None,
    candidate_options: tuple[str, ...] = (),
    reason: str = "Decision policy.",
    requires_confirmation_reason: str | None = None,
) -> AdaptationPolicyDecision:
    return AdaptationPolicyDecision(
        action=action,  # type: ignore[arg-type]
        selected_candidate_id=selected_candidate_id,
        candidate_options=candidate_options,
        reason=reason,
        user_facing_reason=reason,
        requires_confirmation_reason=requires_confirmation_reason,
        risk_level="medium" if action != "commit" else "low",  # type: ignore[arg-type]
    )
