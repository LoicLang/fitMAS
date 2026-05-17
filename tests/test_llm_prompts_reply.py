from __future__ import annotations

from fitmas.llm.prompts.reply import ReplyPromptInput, build_reply_prompt


def test_reply_prompt_uses_backend_facts_and_forbids_invention() -> None:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline="conversation",
            capability="plan_committed",
            user_text="décale à vendredi",
            original_llm_reply="Je le décale.",
            committed_events=("Footing déplacé vendredi.",),
            blocked_events=(),
            pending_summary=None,
            memory_actions_applied=(),
            execution_actions_applied=(),
            allowed_to_claim_mutation=True,
            extra_facts=("before=jeudi", "after=vendredi"),
        )
    )

    assert "Evenements commits:" in rendered.prompt
    assert "Footing déplacé vendredi." in rendered.prompt
    assert "Tu ne dois jamais inventer un commit" in rendered.system
    assert "Reponds uniquement avec le texte final" in rendered.system


def test_reply_prompt_marks_no_commit_as_uncommitted() -> None:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline="conversation",
            capability="plan_pending",
            user_text="allège ce soir",
            original_llm_reply="",
            committed_events=(),
            blocked_events=(),
            pending_summary="Allègement à confirmer.",
            memory_actions_applied=(),
            execution_actions_applied=(),
            allowed_to_claim_mutation=False,
            extra_facts=(),
        )
    )

    assert "Aucun changement planning n'a ete commit." in rendered.prompt
    assert "Confirmation en attente: Allègement à confirmer." in rendered.prompt
    assert "ne claim pas une action appliquee" in rendered.prompt
