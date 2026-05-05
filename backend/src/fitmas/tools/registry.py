from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.execution_context import build_today_execution_context
from fitmas.fact_memory import fact_is_current, select_relevant_facts
from fitmas import plan_patch_tools
from fitmas.planning_window_resolution import format_planning_window_summary, resolve_planning_window_inputs
from fitmas.replan_proposal import build_replan_proposal
from fitmas.time_context import get_local_now, get_timezone
from fitmas.tools.contract import ToolContext, ToolResult, ToolSpec
from fitmas.training_load import compute_ctl_atl_tsb, estimate_tss


def build_tool_registry() -> dict[str, ToolSpec]:
    specs = (
        ToolSpec(
            name="get_today_context",
            description="Retourne le contexte d'execution du jour: prevu, reel, ecart et activites recentes.",
            input_schema={"type": "object", "properties": {}, "required": []},
            allowed_pipelines=("conversation",),
            handler=_get_today_context,
        ),
        ToolSpec(
            name="get_plan_window",
            description="Retourne les seances planifiees sur une fenetre de dates.",
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Date debut ISO YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "Date fin ISO YYYY-MM-DD."},
                    "limit": {"type": "integer", "description": "Nombre max de seances a retourner."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_plan_window,
        ),
        ToolSpec(
            name="resolve_planning_window",
            description="Resout une contrainte temporelle utilisateur contre le vrai planning et retourne les seances candidates.",
            input_schema={
                "type": "object",
                "properties": {
                    "reference_label": {"type": "string", "description": "Label humain, ex: demain soir."},
                    "resolved_date": {"type": "string", "description": "Date visee en ISO YYYY-MM-DD."},
                    "day_key": {"type": "string", "description": "Jour vise si connu, ex: thursday."},
                    "window": {"type": "string", "description": "Fenetre visee: morning, midday, evening."},
                    "scope": {"type": "string", "description": "single_window, single_day ou week."},
                    "limit": {"type": "integer", "description": "Nombre max de seances a retourner."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=_resolve_planning_window_tool,
        ),
        ToolSpec(
            name="get_recent_activities",
            description="Retourne les activites recentes sur N jours.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Nombre de jours a couvrir."},
                    "limit": {"type": "integer", "description": "Nombre max d'activites a retourner."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_recent_activities,
        ),
        ToolSpec(
            name="get_activity_highlights",
            description="Retourne quelques highlights activite: plus longue sortie, plus grande distance, plus rapide.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Fenetre recente en jours pour calculer les highlights."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "heartbeat"),
            handler=_get_activity_highlights,
        ),
        ToolSpec(
            name="get_recent_reality_window",
            description="Retourne un recap planifie vs reel sur une fenetre recente.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Nombre de jours recents a couvrir."},
                    "limit": {"type": "integer", "description": "Nombre max d'elements par bloc."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_recent_reality_window,
        ),
        ToolSpec(
            name="get_load_context",
            description="Retourne un contexte de charge simple: reel recent et planifie proche.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Nombre de jours pour comparer reel recent et planifie proche."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_load_context,
        ),
        ToolSpec(
            name="get_relevant_facts",
            description="Retourne la memoire utile la plus pertinente selon un affect.",
            input_schema={
                "type": "object",
                "properties": {
                    "affects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste d'affects vises, ex: conversation, planning, heartbeat.",
                    },
                    "limit": {"type": "integer", "description": "Nombre max de facts."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_relevant_facts,
        ),
        ToolSpec(
            name="get_user_constraints",
            description="Retourne les contraintes utilisateur actives (indisponibilite, sante, blessure) avec leur date d'expiration.",
            input_schema={
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filtre par categories. Defaut: availability, schedule, constraint, health, fatigue.",
                    },
                    "limit": {"type": "integer", "description": "Nombre max de contraintes."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_user_constraints,
        ),
        ToolSpec(
            name="suggest_replan_candidates",
            description="Suggere des candidates de replan pour une contrainte temporelle ou sportive active, sans ecrire en base. Ce tool n'est pas une autorite de decision: le coach doit transformer la candidate utile en PlanPatch puis laisser le backend valider/commit.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Date debut ISO YYYY-MM-DD si l'user vient d'annoncer la contrainte."},
                    "end_date": {"type": "string", "description": "Date fin ISO YYYY-MM-DD si connue."},
                    "sport_type": {"type": "string", "description": "Sport bloque si connu, ex: swimming."},
                    "preferred_replacement_sport": {"type": "string", "description": "Sport de remplacement prefere si le user l'a deja dit."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_suggest_replan_candidates,
        ),
        ToolSpec(
            name="draft_move_session",
            description=(
                "Construit un PlanPatch candidat pour deplacer une seance existante vers une date cible, "
                "puis le valide sans ecrire en base. Retourne patch + validation. Le coach doit copier le patch "
                "dans CoachDecision; le backend revalide et applique via PlanMutationService."
            ),
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer", "description": "ID ScheduledSession a deplacer."},
                    "target_date": {"type": "string", "description": "Date cible ISO YYYY-MM-DD."},
                    "from_day": {"type": "string", "description": "Jour source si connu."},
                    "to_day": {"type": "string", "description": "Jour cible si connu."},
                    "rationale": {"type": "string", "description": "Raison courte du changement."},
                    "coach_message": {"type": "string", "description": "Message coach associe au patch candidat."},
                    "confirmation_reason": {"type": "string", "description": "Raison de confirmation si le coach veut la demander."},
                },
                "required": ["target_session_id", "target_date", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_move_session,
        ),
        ToolSpec(
            name="draft_swap_sessions",
            description=(
                "Construit un PlanPatch candidat pour echanger deux seances existantes, puis le valide sans ecrire en base. "
                "A utiliser quand deux vraies seances existent deja et que le user veut inverser leurs jours."
            ),
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer", "description": "Premier ID ScheduledSession."},
                    "second_session_id": {"type": "integer", "description": "Second ID ScheduledSession."},
                    "rationale": {"type": "string", "description": "Raison courte de l'echange."},
                    "coach_message": {"type": "string", "description": "Message coach associe au patch candidat."},
                    "confirmation_reason": {"type": "string", "description": "Raison de confirmation si besoin."},
                },
                "required": ["target_session_id", "second_session_id", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_swap_sessions,
        ),
        ToolSpec(
            name="draft_replace_session",
            description=(
                "Construit un PlanPatch candidat pour remplacer le contenu d'une seance existante, puis le valide "
                "sans ecrire en base. Retourne patch + validation; aucun commit n'est effectue."
            ),
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer", "description": "ID ScheduledSession a remplacer."},
                    "new_title": {"type": "string", "description": "Nouveau titre."},
                    "new_goal": {"type": "string", "description": "Nouvel objectif."},
                    "new_sport_type": {"type": "string", "description": "Nouveau sport, ex running/swimming/cycling."},
                    "new_session_type": {"type": "string", "description": "Nouveau type de seance."},
                    "new_duration_min": {"type": "integer", "description": "Nouvelle duree en minutes."},
                    "new_intensity": {"type": "string", "description": "Nouvelle intensite: easy/moderate/hard."},
                    "new_description": {"type": "string", "description": "Description courte."},
                    "rationale": {"type": "string", "description": "Raison courte du remplacement."},
                    "coach_message": {"type": "string", "description": "Message coach associe au patch candidat."},
                    "confirmation_reason": {"type": "string", "description": "Raison de confirmation si besoin."},
                },
                "required": ["target_session_id", "new_sport_type", "new_title", "new_duration_min", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_replace_session,
        ),
        ToolSpec(
            name="draft_lighten_day",
            description=(
                "Construit un PlanPatch candidat pour alleger une seance existante, puis le valide sans ecrire en base. "
                "A utiliser pour fatigue/douleur/recuperation quand la seance reste au planning mais devient plus facile."
            ),
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer", "description": "ID ScheduledSession a alleger."},
                    "new_title": {"type": "string", "description": "Titre ajuste optionnel."},
                    "new_goal": {"type": "string", "description": "Objectif ajuste optionnel."},
                    "new_duration_min": {"type": "integer", "description": "Duree cible optionnelle."},
                    "new_intensity": {"type": "string", "description": "Intensite cible, defaut easy."},
                    "new_description": {"type": "string", "description": "Description courte optionnelle."},
                    "rationale": {"type": "string", "description": "Raison courte de l'allegement."},
                    "coach_message": {"type": "string", "description": "Message coach associe au patch candidat."},
                    "confirmation_reason": {"type": "string", "description": "Raison de confirmation si besoin."},
                },
                "required": ["target_session_id", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_lighten_day,
        ),
        ToolSpec(
            name="draft_create_session",
            description=(
                "Construit un PlanPatch candidat pour creer une nouvelle seance datee, puis le valide sans ecrire en base. "
                "Retourne patch + validation; le backend revalide avant tout commit."
            ),
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Date cible ISO YYYY-MM-DD."},
                    "new_title": {"type": "string", "description": "Titre de la nouvelle seance."},
                    "new_goal": {"type": "string", "description": "Objectif de la nouvelle seance."},
                    "new_sport_type": {"type": "string", "description": "Sport, ex running/swimming/cycling."},
                    "new_session_type": {"type": "string", "description": "Type de seance."},
                    "new_duration_min": {"type": "integer", "description": "Duree en minutes."},
                    "new_intensity": {"type": "string", "description": "Intensite: easy/moderate/hard."},
                    "new_description": {"type": "string", "description": "Description courte."},
                    "rationale": {"type": "string", "description": "Raison courte de creation."},
                    "coach_message": {"type": "string", "description": "Message coach associe au patch candidat."},
                    "confirmation_reason": {"type": "string", "description": "Raison de confirmation si besoin."},
                },
                "required": ["target_date", "new_sport_type", "new_title", "new_duration_min", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_create_session,
        ),
        ToolSpec(
            name="validate_plan_patch",
            description=(
                "Valide un PlanPatch sans l'appliquer. Retourne valid/warning/"
                "requires_confirmation/blocked, les raisons typees et les suggested_fix."
            ),
            kind="validation",
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "description": "PlanPatch complet: coach_message + operations[].",
                    }
                },
                "required": ["patch"],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_validate_plan_patch_tool,
        ),
        ToolSpec(
            name="validate_week_coherence",
            description=(
                "Review sportive validation-only d'un PlanPatch: simule la semaine before/after, "
                "retourne validation runtime, checks deterministes et verdict WeekCoherenceReviewer. "
                "Aucun commit; le backend re-run toujours cette gate avant write."
            ),
            kind="validation",
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "description": "PlanPatch complet: coach_message + operations[].",
                    }
                },
                "required": ["patch"],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_validate_week_coherence_tool,
        ),
        ToolSpec(
            name="propose_replan",
            description="Compat legacy: utilise suggest_replan_candidates. Retourne une candidate de replan read-only, pas une decision finale.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Date debut ISO YYYY-MM-DD si l'user vient d'annoncer la contrainte."},
                    "end_date": {"type": "string", "description": "Date fin ISO YYYY-MM-DD si connue."},
                    "sport_type": {"type": "string", "description": "Sport bloque si connu, ex: swimming."},
                    "preferred_replacement_sport": {"type": "string", "description": "Sport de remplacement prefere si le user l'a deja dit."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=_propose_replan,
        ),
    )
    return {spec.name: spec for spec in specs}


def list_tools_for_pipeline(pipeline: str, *, tool_names: Sequence[str] | None = None) -> list[dict[str, Any]]:
    registry = build_tool_registry()
    if tool_names:
        ordered: list[dict[str, Any]] = []
        for name in tool_names:
            spec = registry.get(name)
            if spec is None or pipeline not in spec.allowed_pipelines:
                continue
            ordered.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "kind": spec.kind,
                    "input_schema": dict(spec.input_schema),
                }
            )
        return ordered
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "kind": spec.kind,
            "input_schema": dict(spec.input_schema),
        }
        for spec in registry.values()
        if pipeline in spec.allowed_pipelines
    ]


def _get_today_context(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    summary = build_today_execution_context(
        timezone_name=context.timezone_name,
        scheduled_sessions=context.scheduled_sessions,
        activities=context.activities,
        now=context.now,
    )
    payload = {
        "local_date": summary.local_date.isoformat(),
        "planned_session_id": summary.planned_session_id,
        "planned_sport": summary.planned_sport,
        "planned_title": summary.planned_title,
        "planned_duration_min": summary.planned_duration_min,
        "execution_status": summary.execution_status,
        "actual_sports_today": list(summary.actual_sports_today),
        "actual_duration_min_today": summary.actual_duration_min_today,
    }
    return ToolResult(
        tool_name="get_today_context",
        status="ok",
        payload=payload,
        summary=f"Aujourd'hui: {summary.execution_status}, sport prevu={summary.planned_sport or 'none'}, sports reels={', '.join(summary.actual_sports_today) or 'none'}.",
    )


def _get_plan_window(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    start_date = _parse_date(arguments.get("start_date")) or local_today
    end_date = _parse_date(arguments.get("end_date")) or (start_date + timedelta(days=6))
    limit = _coerce_int(arguments.get("limit"), default=14, minimum=1, maximum=31)
    items: list[dict[str, Any]] = []
    for session in context.scheduled_sessions:
        local_date = _local_date(_value(session, "scheduled_date"), timezone_name=context.timezone_name)
        if local_date is None or local_date < start_date or local_date > end_date:
            continue
        items.append(
            {
                "id": _value(session, "id"),
                "scheduled_date": local_date.isoformat(),
                "sport_type": _value(session, "sport_type"),
                "session_title": _value(session, "session_title"),
                "duration_min": _value(session, "duration_min"),
                "completion_status": _value(session, "completion_status"),
            }
        )
        if len(items) >= limit:
            break
    return ToolResult(
        tool_name="get_plan_window",
        status="ok",
        payload={"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "sessions": items},
        summary=f"{len(items)} seances entre {start_date.isoformat()} et {end_date.isoformat()}.",
    )


def _get_recent_activities(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    days = _coerce_int(arguments.get("days"), default=7, minimum=1, maximum=90)
    limit = _coerce_int(arguments.get("limit"), default=8, minimum=1, maximum=30)
    cutoff = local_today - timedelta(days=max(0, days - 1))
    items: list[dict[str, Any]] = []
    for activity in context.activities:
        local_date = _local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=context.timezone_name)
        if local_date is None or local_date < cutoff:
            continue
        items.append(
            {
                "id": _value(activity, "id"),
                "local_date": local_date.isoformat(),
                "sport_type": _value(activity, "sport_type"),
                "title": _value(activity, "title"),
                "duration_min": _value(activity, "duration_min"),
                "distance_m": _value(activity, "distance_m"),
                "avg_speed": _value(activity, "avg_speed"),
            }
        )
        if len(items) >= limit:
            break
    return ToolResult(
        tool_name="get_recent_activities",
        status="ok",
        payload={"days": days, "activities": items},
        summary=f"{len(items)} activites sur {days} jours.",
    )


def _resolve_planning_window_tool(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    resolved = resolve_planning_window_inputs(
        reference_label=str(arguments.get("reference_label") or arguments.get("resolved_date") or arguments.get("day_key") or "fenetre"),
        resolved_date=_parse_date(arguments.get("resolved_date")),
        day_key=str(arguments.get("day_key") or "").strip() or None,
        window=str(arguments.get("window") or "").strip() or None,
        scope=str(arguments.get("scope") or "single_window"),
        scheduled_sessions=context.scheduled_sessions,
        timezone_name=context.timezone_name,
        now=context.now,
        limit=_coerce_int(arguments.get("limit"), default=8, minimum=1, maximum=20),
    )
    return ToolResult(
        tool_name="resolve_planning_window",
        status="ok",
        payload={
            "reference_label": resolved.reference_label,
            "scope": resolved.scope,
            "resolved_date": resolved.resolved_date.isoformat() if resolved.resolved_date else None,
            "window": resolved.window,
            "matched_session_id": resolved.matched_session_id,
            "exact_match": resolved.exact_match,
            "needs_clarification": resolved.needs_clarification,
            "clarification_reason": resolved.clarification_reason,
            "candidate_sessions": [
                {
                    "session_id": item.session_id,
                    "scheduled_date": item.scheduled_date.isoformat(),
                    "day_key": item.day_key,
                    "part_of_day": item.part_of_day,
                    "sport_type": item.sport_type,
                    "session_title": item.session_title,
                    "completion_status": item.completion_status,
                    "priority": item.priority,
                }
                for item in resolved.candidate_sessions
            ],
        },
        summary=format_planning_window_summary(resolved),
    )


def _get_activity_highlights(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    recent = _get_recent_activities(context, {"days": arguments.get("days", 30), "limit": 60}).payload["activities"]
    longest_duration = max(recent, key=lambda item: item.get("duration_min") or 0, default=None)
    longest_distance = max(recent, key=lambda item: item.get("distance_m") or 0, default=None)
    fastest = max(recent, key=lambda item: item.get("avg_speed") or 0, default=None)
    payload = {
        "longest_duration": longest_duration,
        "longest_distance": longest_distance,
        "fastest": fastest,
    }
    highlights = sum(1 for item in payload.values() if item)
    return ToolResult(
        tool_name="get_activity_highlights",
        status="ok",
        payload=payload,
        summary=f"{highlights} highlights activite disponibles.",
    )


def _suggest_replan_candidates(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    return _build_replan_candidate_result(
        context,
        arguments,
        tool_name="suggest_replan_candidates",
    )


def _propose_replan(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    return _build_replan_candidate_result(context, arguments, tool_name="propose_replan")


def _validate_plan_patch_tool(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    from fitmas.plan_patch import PlanPatch, validate_plan_patch

    try:
        patch = PlanPatch.model_validate(_raw_patch_payload(arguments))
    except Exception as exc:
        return ToolResult(
            tool_name="validate_plan_patch",
            status="error",
            error=f"invalid_plan_patch: {exc}",
            summary="Patch invalide: schema PlanPatch non respecte.",
        )
    validation = validate_plan_patch(
        context.db,
        plan_id=0,
        patch=patch,
        scheduled_sessions=context.scheduled_sessions,
        timezone_name=context.timezone_name,
    )
    payload = _plan_patch_validation_payload(validation)
    return ToolResult(
        tool_name="validate_plan_patch",
        status="ok",
        payload=payload,
        summary=validation.summary,
    )


def _validate_week_coherence_tool(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    from fitmas.plan_patch import PlanPatch, validate_plan_patch
    from fitmas.week_coherence import aggregate_week_coherence_policy, build_week_coherence_context

    try:
        patch = PlanPatch.model_validate(_raw_patch_payload(arguments))
    except Exception as exc:
        return ToolResult(
            tool_name="validate_week_coherence",
            status="error",
            error=f"invalid_plan_patch: {exc}",
            summary="Patch invalide: schema PlanPatch non respecte.",
        )
    validation = validate_plan_patch(
        context.db,
        plan_id=0,
        patch=patch,
        scheduled_sessions=context.scheduled_sessions,
        timezone_name=context.timezone_name,
    )
    week_context = build_week_coherence_context(
        patch=patch,
        validation=validation,
        scheduled_sessions=context.scheduled_sessions,
        activities=context.activities,
        active_facts=context.active_facts,
        timezone_name=context.timezone_name,
    )
    request_json_fn = None if validation.status == "blocked" else _request_week_coherence_json
    review = review_week_coherence_with_llm(
        week_context,
        request_json_fn=request_json_fn,
    )
    policy_status = aggregate_week_coherence_policy(
        patch_validation=validation,
        week_review=review,
        deterministic_checks=week_context.deterministic_checks,
        allow_requires_confirmation=False,
    )
    payload = {
        "validation": _plan_patch_validation_payload(validation),
        "deterministic_checks": _deterministic_week_checks_payload(week_context.deterministic_checks),
        "review": _week_coherence_review_payload(review),
        "policy_status": policy_status,
        "commit_performed": False,
        "writer": "none",
    }
    return ToolResult(
        tool_name="validate_week_coherence",
        status="ok",
        payload=payload,
        summary=review.summary,
    )


def _raw_patch_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_patch = arguments.get("patch")
    if isinstance(raw_patch, dict):
        return raw_patch
    return {
        "coach_message": str(arguments.get("coach_message") or "Patch a valider."),
        "operations": arguments.get("operations") or [],
        "confirmation_reason": arguments.get("confirmation_reason"),
    }


def _plan_patch_validation_payload(validation: Any) -> dict[str, Any]:
    return {
        "status": validation.status,
        "summary": validation.summary,
        "operation_results": [
            {
                "operation_type": result.operation_type,
                "status": result.status,
                "target_session_id": result.target_session_id,
                "block_reason": result.block_reason,
                "warning_codes": list(result.warning_codes),
                "warning_messages": list(result.warning_messages),
                "suggested_fix": result.suggested_fix,
            }
            for result in validation.operation_results
        ],
    }


def _deterministic_week_checks_payload(checks: Any) -> dict[str, Any]:
    return {
        "hard_sessions_before": checks.hard_sessions_before,
        "hard_sessions_after": checks.hard_sessions_after,
        "min_hard_gap_hours_after": checks.min_hard_gap_hours_after,
        "recovery_sessions_before": checks.recovery_sessions_before,
        "recovery_sessions_after": checks.recovery_sessions_after,
        "key_session_ids_touched": list(checks.key_session_ids_touched),
        "completed_session_ids_touched": list(checks.completed_session_ids_touched),
        "weekly_duration_delta_min": checks.weekly_duration_delta_min,
        "estimated_tss_delta": checks.estimated_tss_delta,
        "change_budget_remaining_before": checks.change_budget_remaining_before,
        "change_budget_remaining_after": checks.change_budget_remaining_after,
        "flags": list(checks.flags),
    }


def _week_coherence_review_payload(review: WeekCoherenceReview) -> dict[str, Any]:
    payload = {
        "status": review.status,
        "sport_quality": review.sport_quality,
        "confidence": review.confidence,
        "summary": review.summary,
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity,
                "detail": finding.detail,
                "target_session_ids": list(finding.target_session_ids),
            }
            for finding in review.findings
        ],
        "suggested_adjustments": [dict(item) for item in review.suggested_adjustments],
        "recommended_policy": review.recommended_policy,
    }
    if review.revised_patch is not None:
        payload["revised_patch"] = review.revised_patch.model_dump(exclude_none=True)
    return payload


def _request_week_coherence_json(**kwargs) -> dict[str, Any] | None:
    from fitmas.plan_mutation_service import _request_week_coherence_json as request_json

    return request_json(**kwargs)


def review_week_coherence_with_llm(context: Any, *, request_json_fn: Any = None) -> Any:
    from fitmas.week_coherence import review_week_coherence_with_llm as review

    return review(context, request_json_fn=request_json_fn)


def _build_replan_candidate_result(
    context: ToolContext,
    arguments: dict[str, Any],
    *,
    tool_name: str,
) -> ToolResult:
    proposal = build_replan_proposal(
        scheduled_sessions=context.scheduled_sessions,
        active_facts=context.active_facts,
        timezone_name=context.timezone_name,
        now=context.now,
        start_date=_parse_date(arguments.get("start_date")),
        end_date=_parse_date(arguments.get("end_date")),
        sport_type=str(arguments.get("sport_type") or "").strip() or None,
        preferred_replacement_sport=str(arguments.get("preferred_replacement_sport") or "").strip() or None,
    )
    if proposal is None:
        return ToolResult(
            tool_name=tool_name,
            status="ok",
            payload={},
            summary="Aucune contrainte exploitable pour suggerer une candidate de replan.",
        )

    mutation = proposal.get("recommended_mutation")
    validation = proposal.get("validation") or {}
    scope = proposal.get("scope") or {}
    impacted_sessions = proposal.get("impacted_sessions") or []
    if not mutation:
        return ToolResult(
            tool_name=tool_name,
            status="ok",
            payload=proposal,
            summary="Contrainte comprise, mais aucune mutation candidate propre n'a ete trouvee.",
        )

    target_title = next(
        (
            item.get("session_title")
            for item in impacted_sessions
            if int(item.get("session_id") or 0) == int(mutation.get("target_session_id") or 0)
        ),
        "seance cible",
    )
    replacement_title = str(mutation.get("new_title") or mutation.get("new_sport_type") or "remplacement")
    validity = "valide" if validation.get("is_valid") else "a confirmer"
    scope_suffix = ""
    if not scope.get("covers_all_impacted_sessions", True):
        remaining = ", ".join(str(item) for item in (scope.get("remaining_session_ids") or []))
        scope_suffix = f" Cette recommandation ne couvre que la seance cible; autres seances encore ouvertes: {remaining or 'oui'}."
    return ToolResult(
        tool_name=tool_name,
        status="ok",
        payload=proposal,
        summary=f"Candidate replan {validity}: remplacer {target_title} par {replacement_title}.{scope_suffix}",
    )


def _get_relevant_facts(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    affects = arguments.get("affects")
    if not isinstance(affects, list):
        affects = ["conversation"]
    limit = _coerce_int(arguments.get("limit"), default=6, minimum=1, maximum=20)
    selected = select_relevant_facts(context.active_facts, affects=affects, limit=limit, now=context.now)
    return ToolResult(
        tool_name="get_relevant_facts",
        status="ok",
        payload={"affects": affects, "facts": selected},
        summary=f"{len(selected)} facts pertinents pour {', '.join(affects)}.",
    )


def _get_recent_reality_window(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    days = _coerce_int(arguments.get("days"), default=7, minimum=1, maximum=30)
    limit = _coerce_int(arguments.get("limit"), default=8, minimum=1, maximum=20)
    start_date = local_today - timedelta(days=max(0, days - 1))

    sessions: list[dict[str, Any]] = []
    for session in context.scheduled_sessions:
        local_date = _local_date(_value(session, "scheduled_date"), timezone_name=context.timezone_name)
        if local_date is None or local_date < start_date or local_date > local_today:
            continue
        sessions.append(
            {
                "id": _value(session, "id"),
                "local_date": local_date.isoformat(),
                "sport_type": _value(session, "sport_type"),
                "session_title": _value(session, "session_title"),
                "duration_min": _value(session, "duration_min"),
                "completion_status": _value(session, "completion_status"),
            }
        )
        if len(sessions) >= limit:
            break

    activities: list[dict[str, Any]] = []
    for activity in context.activities:
        local_date = _local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=context.timezone_name)
        if local_date is None or local_date < start_date or local_date > local_today:
            continue
        activities.append(
            {
                "id": _value(activity, "id"),
                "local_date": local_date.isoformat(),
                "sport_type": _value(activity, "sport_type"),
                "title": _value(activity, "title"),
                "duration_min": _value(activity, "duration_min"),
                "distance_m": _value(activity, "distance_m"),
            }
        )
        if len(activities) >= limit:
            break

    return ToolResult(
        tool_name="get_recent_reality_window",
        status="ok",
        payload={
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": local_today.isoformat(),
            "planned_sessions": sessions,
            "activities": activities,
        },
        summary=f"Fenetre recente {days}j: {len(sessions)} seances planifiees, {len(activities)} activites reelles.",
    )


def _get_load_context(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    days = _coerce_int(arguments.get("days"), default=7, minimum=1, maximum=21)
    recent_start = local_today - timedelta(days=max(0, days - 1))
    upcoming_end = local_today + timedelta(days=max(0, days - 1))

    recent_activities = [
        activity
        for activity in context.activities
        if (local_date := _local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=context.timezone_name))
        is not None
        and recent_start <= local_date <= local_today
    ]
    upcoming_sessions = [
        session
        for session in context.scheduled_sessions
        if (local_date := _local_date(_value(session, "scheduled_date"), timezone_name=context.timezone_name))
        is not None
        and local_today <= local_date <= upcoming_end
        and str(_value(session, "sport_type") or "").lower() != "rest"
    ]

    actual_duration_min = sum(int(_value(activity, "duration_min") or 0) for activity in recent_activities)
    planned_duration_min = sum(int(_value(session, "duration_min") or 0) for session in upcoming_sessions)
    actual_sports = sorted({str(_value(activity, "sport_type") or "") for activity in recent_activities if _value(activity, "sport_type")})
    key_session_count = sum(
        1
        for session in upcoming_sessions
        if any(
            token in f"{_value(session, 'priority') or ''} {_value(session, 'session_title') or ''}".lower()
            for token in ("cle", "qualite", "bloc", "long")
        )
    )

    fitness = _compute_fitness_snapshot(context.activities, as_of_date=local_today)

    return ToolResult(
        tool_name="get_load_context",
        status="ok",
        payload={
            "days": days,
            "recent_actual_duration_min": actual_duration_min,
            "recent_actual_activity_count": len(recent_activities),
            "recent_actual_sports": actual_sports,
            "upcoming_planned_duration_min": planned_duration_min,
            "upcoming_planned_session_count": len(upcoming_sessions),
            "upcoming_key_session_count": key_session_count,
            "as_of_date": fitness["as_of_date"],
            "ctl": fitness["ctl"],
            "atl": fitness["atl"],
            "tsb": fitness["tsb"],
            "fitness_label": fitness["label"],
        },
        summary=(
            f"Charge {days}j: reel {actual_duration_min} min sur {len(recent_activities)} activites, "
            f"planifie {planned_duration_min} min sur {len(upcoming_sessions)} seances. "
            f"CTL {fitness['ctl']} ATL {fitness['atl']} TSB {fitness['tsb']} ({fitness['label']})."
        ),
    )


def _get_user_constraints(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    raw_categories = arguments.get("categories")
    if isinstance(raw_categories, list) and raw_categories:
        categories = {str(item).strip().lower() for item in raw_categories if str(item).strip()}
    else:
        categories = {"availability", "schedule", "constraint", "health", "fatigue"}
    limit = _coerce_int(arguments.get("limit"), default=8, minimum=1, maximum=30)
    items: list[dict[str, Any]] = []
    for fact in context.active_facts:
        category = str(_value(fact, "category") or "").strip().lower()
        if category not in categories:
            continue
        if not fact_is_current(fact, now=context.now):
            continue
        expires_at = _value(fact, "expires_at")
        items.append(
            {
                "category": category,
                "key": _value(fact, "key"),
                "value": _value(fact, "value"),
                "urgency": _value(fact, "urgency"),
                "confirmed": bool(_value(fact, "confirmed")),
                "expires_at": _datetime_iso(expires_at),
            }
        )
        if len(items) >= limit:
            break
    return ToolResult(
        tool_name="get_user_constraints",
        status="ok",
        payload={"categories": sorted(categories), "constraints": items},
        summary=f"{len(items)} contraintes actives ({', '.join(sorted(categories))}).",
    )


def _compute_fitness_snapshot(
    activities: Sequence[Any], *, as_of_date: date
) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    for activity in activities:
        tss = _value(activity, "tss")
        if tss is None:
            tss = estimate_tss(activity)
        enriched.append(
            {
                "started_at": _value(activity, "started_at") or _value(activity, "created_at"),
                "tss": tss,
            }
        )
    snapshot = compute_ctl_atl_tsb(enriched, as_of_date=as_of_date)
    tsb = float(snapshot.get("tsb") or 0.0)
    if tsb > 5:
        label = "frais"
    elif tsb < -10:
        label = "fatigue"
    else:
        label = "neutre"
    return {
        "as_of_date": snapshot.get("as_of_date") or as_of_date.isoformat(),
        "ctl": snapshot.get("ctl") or 0.0,
        "atl": snapshot.get("atl") or 0.0,
        "tsb": snapshot.get("tsb") or 0.0,
        "label": label,
    }


def _datetime_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value or None
    return None


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _local_date(value: Any, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    timezone = get_timezone(timezone_name)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(timezone).date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(timezone).date()
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
