from __future__ import annotations

from fitmas.legacy.llm.prompts.understanding import UnderstandingPromptInput, build_understanding_prompt


def test_understanding_prompt_outputs_coach_understanding_only() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="telegram user_message: j'ai mal dormi, je peux alléger ce soir ?",
            context_blocks=("today: 2026-05-14", "plan: séance intense ce soir"),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"
    assert "CoachUnderstanding" in text
    assert "fitmas_message" not in text
    assert "PlanPatch" not in text
    assert "MutationDecision" not in text
    assert "ne parles pas au user" in text


def test_understanding_prompt_contains_requested_change_shape() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="telegram user_message: décale la séance à vendredi",
            context_blocks=("plan: jeudi tempo id=12",),
        )
    )

    assert '"intent"' in rendered.prompt
    assert '"requested_change"' in rendered.prompt
    assert '"pending_resolution"' in rendered.prompt
    assert '"clarification_need"' in rendered.prompt


def test_understanding_prompt_forbids_visible_speech_and_writes() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="source=telegram type=user_message text=deplace demain",
            context_blocks=("Plan compact",),
        )
    )
    text = f"{rendered.system}\n{rendered.prompt}"

    assert "Tu ne parles pas au user" in text
    assert "Tu ne composes aucun message visible" in text
    assert "Tu ne produis pas de patch planning" in text
    assert "PlanPatch" not in text
    assert "fitmas_message" not in text


def test_understanding_prompt_documents_command_payload_fields_without_commands() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="message: je ne peux pas nager deux semaines",
            context_blocks=("plan compact",),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"

    assert "payload" in text
    assert "action_type" in text
    assert "record_availability" in text
    assert "record_health_signal" in text
    assert "record_execution_update" in text
    assert "commande DB" in text
    assert "Command" not in text
    assert "PlanPatch" not in text


def test_understanding_prompt_requires_pending_resolution_when_pending_active() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="source=telegram type=user_message pending_active=True text=non finalement on laisse",
            context_blocks=("Pending confirmation: plan_patch id=12",),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"

    assert "pending_active=True" in text
    assert "intent=pending_response" in text
    assert "pending_resolution" in text
