from __future__ import annotations

from fitmas.decision import plan_patch_reply


def pending_confirmation_context_for_prompt(pending_confirmation) -> str | None:
    if pending_confirmation is None:
        return None
    reason = plan_patch_reply.safe_user_visible_pending_text(str(pending_confirmation.reason or "").strip())
    summary = plan_patch_reply.safe_user_visible_pending_text(str(pending_confirmation.summary or "").strip())
    mutation_type = str(pending_confirmation.mutation_type or "").strip()
    choice_instructions: tuple[str, ...] = ()
    if mutation_type == "plan_patch_choice":
        choice_instructions = (
            "- ce pending contient plusieurs options candidates structurees.",
            "- si le user choisit une option, retourne `pending_resolution.type=accept_pending` "
            "avec `selected_candidate_id` egal a l'id exact de l'option choisie.",
            "- si le choix est ambigu, retourne `pending_resolution.type=needs_clarification`.",
        )
    lines = [
        "Confirmation planning en attente (artefact machine, pas une decision deja appliquee):",
        f"- id: {pending_confirmation.id}",
        f"- type: {mutation_type}",
        f"- raison: {reason}",
        f"- resume: {summary}",
        "- lis le nouveau message dans ce contexte et decide toi-meme.",
        "- si le user accepte clairement, retourne `pending_resolution.type=accept_pending`.",
        "- si le user refuse, retourne `pending_resolution.type=reject_pending`.",
        "- si le user modifie la demande, retourne `modify_pending` avec requested_changes; ne forge pas un nouveau patch libre.",
        "- si le user parle d'autre chose, retourne `ignore` et reponds au nouveau message.",
        *choice_instructions,
        f"- payload: {pending_confirmation.decision_json}",
    ]
    return "\n".join(lines) + "\n"


def should_route_availability_context_to_llm(
    turn_plan,
    *,
    week_scope_reply: str | None,
    no_candidate_reply: str | None,
) -> bool:
    return week_scope_reply is not None or no_candidate_reply is not None


def should_route_adaptation_context_to_llm(
    turn_plan,
    adaptation,
    *,
    plan_mutation_request: bool = False,
) -> bool:
    return adaptation is not None


def adaptation_context_for_prompt(adaptation) -> str | None:
    if adaptation is None:
        return None
    scenario = adaptation.selected_scenario
    mutation = scenario.mutation
    lines = [
        "Adaptation candidate deterministe:",
        f"- raison: {adaptation.event.reason_code.value}",
        f"- confiance: {adaptation.event.confidence}",
        f"- mutation candidate: {mutation.mutation_type}",
        f"- session cible: {mutation.target_session_id}",
        f"- date cible: {mutation.target_date}",
        f"- resume: {scenario.summary}",
        f"- message candidate: {adaptation.user_message}",
        "- utilise cette candidate comme option valide, mais arbitre la reponse finale selon le message utilisateur",
    ]
    return "\n".join(lines)


def availability_context_for_prompt(*, week_scope_reply: str | None, no_candidate_reply: str | None) -> str | None:
    reply = week_scope_reply or no_candidate_reply
    if not reply:
        return None
    return (
        "Contexte orchestration planning:\n"
        f"- grounding deterministe: {reply}\n"
        "- utilise ce grounding comme verite de contexte, mais formule toi-meme la reponse finale\n"
        "- si aucune mutation sure n'est applicable, garde mutation_type=no_change et explique sobrement"
    )


def append_prompt_section(base: str, section: str | None) -> str:
    if not section:
        return base
    return "\n".join(part for part in (base, section) if part)
