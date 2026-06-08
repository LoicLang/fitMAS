from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from fitmas.legacy.decision import RequestedPlanChange
from fitmas.legacy.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.legacy.domain.planning.evaluator import PlanCandidateEvaluator
from fitmas.legacy.domain.planning.models import PlanningDecisionResult
from fitmas.legacy.domain.planning.policy import SportPolicy
from fitmas.legacy.domain.planning.reference_resolver import ReferenceResolver
from fitmas.legacy.domain.planning.reviewer import review_plan_patch_candidates


def decide_plan_change(
    requested_change: RequestedPlanChange,
    *,
    context: Any,
    db: Session,
    user: Any,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningDecisionResult:
    resolved = ReferenceResolver(context).resolve(requested_change)
    if any(item.startswith("unresolved") for item in resolved.warnings):
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=_block_reason_from_unresolved_refs(resolved),
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )

    hard_create_block_reason = _hard_create_block_reason(resolved, context)
    if hard_create_block_reason is not None:
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=hard_create_block_reason,
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )

    create_target_block_reason = _create_target_block_reason(resolved, context)
    if create_target_block_reason is not None:
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=create_target_block_reason,
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )

    candidate_set = PlanCandidateBuilder(context).build(resolved)
    if not candidate_set.candidates:
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=_block_reason_from_empty_candidate_set(resolved),
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )
    scheduled_sessions = tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())
    activities = tuple(getattr(getattr(context, "execution", None), "activities", ()) or ())
    active_facts = tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ())
    evaluated = PlanCandidateEvaluator(db=db, user=user).evaluate(
        candidate_set,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        active_facts=active_facts,
        coach_state_bundle=coach_state_bundle,
    )
    reviewer_decision = None
    if reviewer_request_json_fn is not None:
        reviewer_decision = review_plan_patch_candidates(evaluated, request_json_fn=reviewer_request_json_fn)
    policy_decision = SportPolicy().decide(
        evaluated,
        reviewer_decision=reviewer_decision,
        force_confirmation_reason=_force_confirmation_reason(resolved),
    )
    selected = _selected_evaluated(policy_decision.selected_candidate_id, evaluated)
    selected_patch = getattr(selected, "patch", None) if selected is not None else None
    return PlanningDecisionResult(
        kind=policy_decision.action,
        selected_candidate_id=policy_decision.selected_candidate_id,
        candidate_options=policy_decision.candidate_options,
        reason=policy_decision.requires_confirmation_reason or policy_decision.reason,
        policy_decision=policy_decision,
        selected_patch=selected_patch,
        evaluated_candidates=tuple(evaluated),
        command_result=None,
        pending_confirmation_id=None,
    )


def _selected_evaluated(selected_candidate_id: str | None, evaluated: tuple[Any, ...]) -> Any | None:
    if selected_candidate_id is None:
        return None
    return next((candidate for candidate in evaluated if candidate.candidate.id == selected_candidate_id), None)


def _block_reason_from_unresolved_refs(resolved) -> str:
    if "unresolved_source_ref" in resolved.warnings:
        date_label = _reference_date_label(resolved.source)
        if date_label:
            return (
                f"Je ne trouve pas de seance planifiee le {date_label}. "
                "Je ne touche pas au plan."
            )
        return "Je ne trouve pas la seance cible a modifier. Je ne touche pas au plan."
    if "unresolved_target_ref" in resolved.warnings:
        date_label = _reference_date_label(resolved.target)
        if date_label:
            return f"Je ne peux pas utiliser le {date_label} comme cible. Je ne touche pas au plan."
        return "Je ne trouve pas la cible du changement. Je ne touche pas au plan."
    return "Je ne peux pas resoudre ce changement planning. Je ne touche pas au plan."


def _block_reason_from_empty_candidate_set(resolved) -> str:
    source = resolved.source
    if resolved.kind == "create":
        target_label = _reference_date_label(resolved.target)
        if target_label:
            return f"Il me manque le sport cible pour creer une seance le {target_label}. Je ne touche pas au plan."
    if source.kind == "sport_window":
        sport_type = _sport_label(getattr(source, "sport_type", None))
        starts_on = _date_label(getattr(source, "starts_on", None))
        ends_on = _date_label(getattr(source, "ends_on", None))
        if starts_on and ends_on:
            return (
                f"Je ne trouve aucune seance de {sport_type} planifiee entre {starts_on} et {ends_on}. "
                "Je ne touche pas au plan."
            )
    if source.kind == "availability_window":
        starts_on = _date_label(getattr(source, "starts_on", None))
        ends_on = _date_label(getattr(source, "ends_on", None))
        if starts_on and ends_on:
            return (
                f"Je note la contrainte du {starts_on} au {ends_on}. "
                "Je ne trouve pas de deplacement coherent et confirme pour cette fenetre. Je ne touche pas au plan."
            )
    return "Aucune option d'adaptation valide."


def _force_confirmation_reason(resolved) -> str | None:
    if resolved.kind == "constraint_window" and resolved.source.kind == "availability_window":
        return "Fenetre large: confirmation requise avant de deplacer plusieurs seances."
    return None


def _hard_create_block_reason(resolved, context: Any) -> str | None:
    if resolved.kind != "create":
        return None
    requested = resolved.requested_change
    if _normalized_intensity(getattr(requested, "desired_intensity", None)) != "hard":
        return None
    target_date = getattr(resolved.target, "date", None)
    if target_date is None:
        return None
    if not _hard_create_is_structurally_unsafe(context, target_date=target_date):
        return None
    return (
        f"Je ne rajoute pas de seance dure le {target_date.isoformat()}: "
        "la semaine a deja une charge intense trop proche. Je ne touche pas au plan."
    )


def _create_target_block_reason(resolved, context: Any) -> str | None:
    if resolved.kind != "create":
        return None
    target_date = getattr(resolved.target, "date", None)
    if target_date is None:
        return None
    if not _has_occupied_training_target(_scheduled_sessions(context), target_date=target_date):
        return None
    return (
        f"Je ne rajoute pas de seance le {target_date.isoformat()}: "
        "une seance stable est deja prevue ce jour-la. Je ne touche pas au plan."
    )


def _hard_create_is_structurally_unsafe(context: Any, *, target_date: date) -> bool:
    sessions = _scheduled_sessions(context)
    if _has_occupied_training_target(sessions, target_date=target_date):
        return True
    hard_dates = tuple(
        session_date
        for session in sessions
        if _is_active_session(session)
        if (session_date := _session_date(session)) is not None
        if _is_hard_session(session)
    )
    if len(hard_dates) + 1 > 3:
        return True
    return any(abs((target_date - hard_date).days) * 24 < 36 for hard_date in hard_dates)


def _scheduled_sessions(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())


def _has_occupied_training_target(sessions: tuple[Any, ...], *, target_date: date) -> bool:
    for session in sessions:
        if not _is_active_session(session):
            continue
        if _session_date(session) != target_date:
            continue
        sport_type = str(_value(session, "sport_type") or "").strip().lower()
        session_type = str(_value(session, "session_type") or "").strip().lower()
        flexibility = str(_value(session, "flexibility") or "").strip().lower()
        if sport_type in {"", "rest", "off"}:
            continue
        if session_type in {"rest", "recovery", "mobility"}:
            continue
        if flexibility == "flexible":
            continue
        return True
    return False


def _is_active_session(session: Any) -> bool:
    status = str(_value(session, "completion_status") or "").strip().lower()
    return status not in {"done", "completed", "skipped", "canceled", "cancelled"}


def _is_hard_session(session: Any) -> bool:
    intensity = str(_value(session, "intensity") or "").strip().lower()
    if intensity in {"hard", "key", "threshold"}:
        return True
    session_type = str(_value(session, "session_type") or "").strip().lower()
    if session_type in {"threshold", "interval", "intervals", "tempo", "long"}:
        return True
    priority = str(_value(session, "priority") or "").strip().lower()
    return "cle" in priority or "key" in priority


def _session_date(session: Any) -> date | None:
    raw = _value(session, "scheduled_date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _normalized_intensity(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return {
        "facile": "easy",
        "easy": "easy",
        "leger": "easy",
        "legere": "easy",
        "light": "easy",
        "modere": "moderate",
        "moderee": "moderate",
        "moderate": "moderate",
        "controle": "moderate",
        "controlee": "moderate",
        "dur": "hard",
        "dure": "hard",
        "hard": "hard",
        "high": "hard",
        "intense": "hard",
        "intensive": "hard",
        "exigeant": "hard",
        "exigeante": "hard",
        "soutenu": "hard",
        "soutenue": "hard",
    }.get(text, text)


def _sport_label(raw: object) -> str:
    value = str(raw or "").strip()
    return {
        "swimming": "natation",
        "cycling": "velo",
        "running": "course",
        "strength": "renforcement",
        "mobility": "mobilite",
    }.get(value, value or "ce sport")


def _reference_date_label(ref) -> str | None:
    return _date_label(getattr(ref, "date", None))


def _date_label(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
