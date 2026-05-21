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


def test_reply_prompt_treats_dated_execution_actions_as_authoritative() -> None:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline="conversation",
            capability="execution_report",
            user_text="je n'ai pas pu la faire hier",
            original_llm_reply="On reste sur la séance d'aujourd'hui.",
            committed_events=(),
            blocked_events=(),
            pending_summary=None,
            memory_actions_applied=(),
            execution_actions_applied=("Renfo support du 2026-04-29 notee comme non faite.",),
            allowed_to_claim_mutation=False,
            extra_facts=(),
        )
    )

    assert "Renfo support du 2026-04-29 notee comme non faite." in rendered.prompt
    assert "source de verite pour la seance, le statut et la date" in rendered.prompt
    assert "ne la transforme pas en aujourd'hui, demain ou hier" in rendered.prompt
