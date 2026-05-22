from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import repository as root_repo, schema as s
from fitmas.domain.planning import repository as repo
from fitmas.domain.planning import mutation_executor
from fitmas.domain.planning import session_actions as plan_actions
from fitmas.domain.planning.mutation_decision import MutationDecision
from fitmas.domain.planning.mutation_hooks import run_pre_mutation_hooks
from fitmas.domain.planning.plan_patch import (
    PlanPatch,
    PlanPatchOperation,
    PlanPatchValidation,
    adapt_plan_patch_to_mutation_decisions,
    validate_plan_patch,
)
from fitmas.domain.planning.week_coherence import (
    WeekCoherenceContext,
    WeekCoherenceReview,
    aggregate_week_coherence_policy,
    build_week_coherence_context,
    review_week_coherence_with_llm,
)


@dataclass(frozen=True, slots=True)
class PlanMutationServiceResult:
    plan_id: int
    applied_count: int
    attempted_count: int
    event_count: int = 0
    applied_events: tuple[PlanAppliedMutationEvent, ...] = ()
    blocked_events: tuple[PlanBlockedMutationEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanPatchServiceResult:
    validation: PlanPatchValidation
    patch: PlanPatch | None = None
    mutation_result: PlanMutationServiceResult | None = None
    week_review: WeekCoherenceReview | None = None
    week_policy_status: str | None = None


@dataclass(frozen=True, slots=True)
class PlanAppliedMutationEvent:
    command_type: str
    user_visible_summary: str
    event_id: int | None = None
    target_session_id: int | None = None
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PlanBlockedMutationEvent:
    """Surface pre-hook rejection details to the caller.

    Carries the mutation_type, the typed `block_reason` from the hook
    (e.g. `same_sport_proximity`, `occupied_training_target`),
    and the warning messages so the caller
    can craft a reason-specific reply instead of a generic fallback.
    """
    command_type: str
    block_reason: str | None
    target_session_id: int | None = None
    second_session_id: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanSessionActionResult:
    action_type: str
    source: str
    session: s.ScheduledSession
    event_id: int | None = None


def apply_decisions_for_user(
    db: Session,
    *,
    user: s.User,
    decisions: Sequence[MutationDecision],
    source: str = "conversation",
    trigger_type: str = "mutation_decision",
    explained_to_user: bool = False,
    conversation_turn_id: int | None = None,
) -> PlanMutationServiceResult | None:
    if not decisions:
        return None

    plan = None
    plan_id = 0
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    applied_count = 0
    event_count = 0
    applied_events: list[PlanAppliedMutationEvent] = []
    blocked_events: list[PlanBlockedMutationEvent] = []
    for decision in decisions:
        if decision.mutation_type == "create_session":
            create_result = _apply_create_session_decision(
                db,
                user=user,
                plan=plan,
                decision=decision,
                source=source,
                trigger_type=trigger_type,
                explained_to_user=explained_to_user,
                conversation_turn_id=conversation_turn_id,
                scheduled_sessions=scheduled_sessions,
            )
            if create_result is not None:
                applied_count += create_result.applied_count
                event_count += create_result.event_count
                applied_events.extend(create_result.applied_events)
                blocked_events.extend(create_result.blocked_events)
            continue
        before_snapshot = (
            _session_snapshot(_scheduled_session_by_id(scheduled_sessions, decision.target_session_id))
            if decision.target_session_id is not None
            else {}
        )
        pre_result, post_result = mutation_executor.apply(
            db,
            plan_id,
            decision,
            user=user,
            scheduled_sessions=scheduled_sessions,
            timezone_name=getattr(user, "timezone", None),
        )
        if not pre_result.allowed:
            warning_messages = tuple(
                getattr(w, "message", "") for w in (getattr(pre_result, "warnings", ()) or ())
            )
            blocked_events.append(
                PlanBlockedMutationEvent(
                    command_type=decision.mutation_type,
                    block_reason=getattr(pre_result, "block_reason", None),
                    target_session_id=decision.target_session_id,
                    second_session_id=decision.second_session_id,
                    warnings=warning_messages,
                )
            )
        if pre_result.allowed and post_result is not None:
            applied_count += 1
            updated_session = (
                repo.get_scheduled_session(db, user.id, decision.target_session_id)
                if decision.target_session_id is not None
                else None
            )
            second_updated_session = (
                repo.get_scheduled_session(db, user.id, decision.second_session_id)
                if decision.second_session_id is not None
                else None
            )
            after_snapshot = _session_snapshot(updated_session)
            user_visible_summary = _build_user_visible_summary(
                decision,
                updated_session,
                second_updated_session,
            )
            event = repo.add_plan_mutation_event(
                db,
                user_id=user.id,
                source=source,
                trigger_type=trigger_type,
                command_type=decision.mutation_type,
                target_session_ids=_decision_session_ids(decision),
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                reason={"rationale": decision.rationale} if decision.rationale else {},
                impact=_jsonable_dict(post_result),
                user_visible_summary=user_visible_summary,
                explained_to_user=explained_to_user,
                conversation_turn_id=conversation_turn_id,
            )
            event_count += 1
            applied_events.append(
                PlanAppliedMutationEvent(
                    command_type=decision.mutation_type,
                    target_session_id=decision.target_session_id,
                    user_visible_summary=user_visible_summary,
                    event_id=_event_id(event),
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                )
            )

    return PlanMutationServiceResult(
        plan_id=plan_id,
        applied_count=applied_count,
        attempted_count=len(decisions),
        event_count=event_count,
        applied_events=tuple(applied_events),
        blocked_events=tuple(blocked_events),
    )


def _apply_create_session_decision(
    db: Session,
    *,
    user: s.User,
    plan: Any,
    decision: MutationDecision,
    source: str,
    trigger_type: str,
    explained_to_user: bool,
    conversation_turn_id: int | None,
    scheduled_sessions: Sequence[Any],
) -> PlanMutationServiceResult:
    plan_id = int(getattr(plan, "id", 0) or 0)
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="create_session",
                target_date=decision.target_date,
                new_sport_type=decision.new_sport_type,
                new_session_type=decision.new_session_type,
                new_title=decision.new_title,
                new_goal=decision.new_goal,
                new_duration_min=decision.new_duration_min,
                new_intensity=decision.new_intensity,
                new_description=decision.new_description,
                rationale=decision.rationale,
            )
        ],
        coach_message=decision.fitmas_message,
    )
    validation = validate_plan_patch(
        db,
        plan_id=plan_id,
        patch=patch,
        scheduled_sessions=scheduled_sessions,
        timezone_name=getattr(user, "timezone", None),
    )
    if validation.status != "valid":
        blocked = validation.operation_results[0] if validation.operation_results else None
        return PlanMutationServiceResult(
            plan_id=plan_id,
            applied_count=0,
            attempted_count=1,
            blocked_events=(
                PlanBlockedMutationEvent(
                    command_type="create_session",
                    block_reason=blocked.block_reason if blocked else validation.status,
                    target_session_id=None,
                    warnings=blocked.warning_messages if blocked else (),
                ),
            ),
        )
    event = _apply_create_session_operation(
        db,
        user=user,
        plan=plan,
        operation=patch.operations[0],
        coach_message=patch.coach_message,
        source=source,
        trigger_type=trigger_type,
        explained_to_user=explained_to_user,
        conversation_turn_id=conversation_turn_id,
    )
    return PlanMutationServiceResult(
        plan_id=plan_id,
        applied_count=1 if event is not None else 0,
        attempted_count=1,
        event_count=1 if event is not None else 0,
        applied_events=(event,) if event is not None else (),
    )


def apply_patch_for_user(
    db: Session,
    *,
    user: s.User,
    patch: PlanPatch,
    source: str = "conversation",
    trigger_type: str = "plan_patch",
    explained_to_user: bool = False,
    conversation_turn_id: int | None = None,
    allow_requires_confirmation: bool = False,
    coach_state_bundle: Any | None = None,
    activities: Sequence[Any] | None = None,
    active_facts: Sequence[Any] | None = None,
) -> PlanPatchServiceResult:
    plan = None
    plan_id = 0
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    if plan is None:
        patch = _normalize_targetless_replace_to_create(patch)
    validation = validate_plan_patch(
        db,
        plan_id=plan_id,
        patch=patch,
        scheduled_sessions=scheduled_sessions,
        timezone_name=getattr(user, "timezone", None),
    )
    if validation.status == "blocked":
        return PlanPatchServiceResult(validation=validation, patch=patch, week_policy_status="blocked")

    week_context = build_week_coherence_context(
        patch=patch,
        validation=validation,
        scheduled_sessions=scheduled_sessions,
        coach_state_bundle=coach_state_bundle,
        activities=activities if activities is not None else _recent_activities_for_week_review(db, user.id),
        active_facts=active_facts if active_facts is not None else _active_facts_for_week_review(db, user.id),
        timezone_name=getattr(user, "timezone", None),
    )
    week_review = _review_patch_week_coherence(week_context)
    week_policy_status = aggregate_week_coherence_policy(
        patch_validation=validation,
        week_review=week_review,
        deterministic_checks=week_context.deterministic_checks,
        allow_requires_confirmation=allow_requires_confirmation,
    )
    if week_policy_status != "valid":
        return PlanPatchServiceResult(
            validation=validation,
            patch=patch,
            week_review=week_review,
            week_policy_status=week_policy_status,
        )

    if not _validation_allows_patch_commit(validation, allow_requires_confirmation=allow_requires_confirmation):
        return PlanPatchServiceResult(
            validation=validation,
            patch=patch,
            week_review=week_review,
            week_policy_status="requires_confirmation",
        )

    legacy_operations = [
        operation for operation in patch.operations if operation.operation_type != "create_session"
    ]
    create_operations = [
        operation for operation in patch.operations if operation.operation_type == "create_session"
    ]
    applied_events: list[PlanAppliedMutationEvent] = []
    blocked_events: list[PlanBlockedMutationEvent] = []
    applied_count = 0
    event_count = 0

    if legacy_operations:
        legacy_result = apply_decisions_for_user(
            db,
            user=user,
            decisions=adapt_plan_patch_to_mutation_decisions(
                PlanPatch(operations=legacy_operations, coach_message=patch.coach_message)
            ),
            source=source,
            trigger_type=trigger_type,
            explained_to_user=explained_to_user,
            conversation_turn_id=conversation_turn_id,
        )
        if legacy_result is not None:
            applied_count += legacy_result.applied_count
            event_count += legacy_result.event_count
            applied_events.extend(legacy_result.applied_events)
            blocked_events.extend(legacy_result.blocked_events)

    for operation in create_operations:
        event = _apply_create_session_operation(
            db,
            user=user,
            plan=plan,
            operation=operation,
            coach_message=patch.coach_message,
            source=source,
            trigger_type=trigger_type,
            explained_to_user=explained_to_user,
            conversation_turn_id=conversation_turn_id,
        )
        if event is not None:
            applied_count += 1
            event_count += 1
            applied_events.append(event)

    mutation_result = PlanMutationServiceResult(
        plan_id=plan_id,
        applied_count=applied_count,
        attempted_count=len(patch.operations),
        event_count=event_count,
        applied_events=tuple(applied_events),
        blocked_events=tuple(blocked_events),
    )
    return PlanPatchServiceResult(
        validation=validation,
        patch=patch,
        mutation_result=mutation_result,
        week_review=week_review,
        week_policy_status=week_policy_status,
    )


def _review_patch_week_coherence(context: WeekCoherenceContext) -> WeekCoherenceReview:
    return review_week_coherence_with_llm(context, request_json_fn=_request_week_coherence_json)


def _request_week_coherence_json(**kwargs) -> dict[str, Any] | None:
    import fitmas.llm.gateway as gw

    context = kwargs.get("context") or {}
    context_json = json.dumps(context, ensure_ascii=False, default=str)
    return gw.request_json(
        system=(
            "Tu es WeekCoherenceReviewer, reviewer sportif subordonne FitMAS. "
            "Tu ne parles pas au user, tu ne commit rien, tu respectes les hard blocks. "
            "Retourne uniquement le JSON demande."
        ),
        prompt=(
            "Juge si ce PlanPatch garde une bonne logique sportive. "
            "Champs obligatoires: status, sport_quality, confidence, summary, "
            "findings, suggested_adjustments, recommended_policy.\n\n"
            "Valeurs autorisees:\n"
            "- status: valid | warning | requires_confirmation | blocked\n"
            "- sport_quality: good | acceptable | fragile | poor\n"
            "- recommended_policy: commit_original | confirm_original | block_original | retry_with_revised_patch | confirm_revised\n\n"
            f"Contexte JSON:\n{context_json}"
        ),
        max_tokens=900,
    )


def _recent_activities_for_week_review(db: Session, user_id: int) -> tuple[Any, ...]:
    try:
        return tuple(root_repo.get_activities(db, user_id, limit=120))
    except Exception:
        return ()


def _active_facts_for_week_review(db: Session, user_id: int) -> tuple[dict[str, Any], ...]:
    try:
        rows = root_repo.get_active_memory_items(
            db,
            user_id,
            profile_limit=24,
            working_limit=24,
            include_patterns=True,
            pattern_limit=6,
            total_limit=36,
        )
    except Exception:
        return ()
    payloads: list[dict[str, Any]] = []
    for row in rows:
        try:
            payloads.append(root_repo.to_pydantic_fact(row).model_dump())
        except Exception:
            continue
    return tuple(payloads)


def _normalize_targetless_replace_to_create(patch: PlanPatch) -> PlanPatch:
    operations: list[PlanPatchOperation] = []
    changed = False
    for operation in patch.operations:
        if (
            operation.operation_type == "replace_session"
            and operation.target_session_id is None
            and operation.target_date
            and operation.new_sport_type
            and operation.new_title
            and operation.new_duration_min
        ):
            operations.append(operation.model_copy(update={"operation_type": "create_session"}))
            changed = True
        else:
            operations.append(operation)
    if not changed:
        return patch
    return PlanPatch(
        operations=operations,
        coach_message=patch.coach_message,
        confirmation_reason=patch.confirmation_reason,
    )


def _validation_allows_patch_commit(
    validation: PlanPatchValidation,
    *,
    allow_requires_confirmation: bool,
) -> bool:
    if validation.status == "valid":
        return True
    return bool(allow_requires_confirmation and validation.status in {"warning", "requires_confirmation"})


def _apply_create_session_operation(
    db: Session,
    *,
    user: s.User,
    plan: Any,
    operation: PlanPatchOperation,
    coach_message: str,
    source: str,
    trigger_type: str,
    explained_to_user: bool,
    conversation_turn_id: int | None,
) -> PlanAppliedMutationEvent | None:
    target_date = _parse_target_date(operation.target_date)
    if target_date is None:
        return None
    session = plan_actions.create_session(
        db,
        user=user,
        target_date=target_date,
        sport_type=str(operation.new_sport_type or "running"),
        session_type=str(operation.new_session_type or "easy"),
        title=str(operation.new_title or "Seance ajoutee"),
        goal=str(operation.new_goal or operation.new_title or "Seance ajoutee"),
        duration_min=operation.new_duration_min,
        intensity=str(operation.new_intensity or "easy"),
        description=str(operation.new_description or ""),
        rationale=operation.rationale,
        source_plan_created_at=getattr(plan, "created_at", None),
    )
    summary = _build_create_session_summary(operation, session, coach_message=coach_message)
    after_snapshot = _session_snapshot(session)
    event = repo.add_plan_mutation_event(
        db,
        user_id=user.id,
        source=source,
        trigger_type=trigger_type,
        command_type="create_session",
        target_session_ids=[int(session.id)],
        before_snapshot={},
        after_snapshot=after_snapshot,
        reason={"rationale": operation.rationale} if operation.rationale else {},
        impact={},
        user_visible_summary=summary,
        explained_to_user=explained_to_user,
        conversation_turn_id=conversation_turn_id,
    )
    return PlanAppliedMutationEvent(
        command_type="create_session",
        target_session_id=int(session.id),
        user_visible_summary=summary,
        event_id=_event_id(event),
        before_snapshot={},
        after_snapshot=after_snapshot,
    )


def complete_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="complete_session",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="complete_session", source=source, session=session, event_id=_event_id(event))


def skip_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.skip_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="skip_session",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="skip_session", source=source, session=session, event_id=_event_id(event))


def move_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    target_date: date | None,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    if target_date is not None:
        scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
        pre_result = run_pre_mutation_hooks(
            db,
            0,
            MutationDecision(
                mutation_type="move_session",
                target_session_id=session_id,
                target_date=target_date.isoformat(),
                rationale=f"source={source}",
                fitmas_message="",
            ),
            scheduled_sessions=scheduled_sessions,
            timezone_name=getattr(user, "timezone", None),
        )
        if not pre_result.allowed:
            return None
    session = plan_actions.move_session(db, user=user, session_id=session_id, target_date=target_date)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="move_session",
        session=session,
        before_snapshot=before,
        reason={"target_date": target_date.isoformat()} if target_date else {},
    )
    return PlanSessionActionResult(action_type="move_session", source=source, session=session, event_id=_event_id(event))


def mark_session_completed_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int | None,
    source: str,
) -> PlanSessionActionResult | None:
    if session_id is None:
        return None
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="activity_completed",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="activity_completed", source=source, session=session, event_id=_event_id(event))


def complete_session_from_activity_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int | None,
    plan_id: int | None,
    matched_day: str | None,
    source: str,
) -> PlanSessionActionResult | None:
    if session_id is None:
        return None
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    reason: dict[str, Any] = {}
    if matched_day:
        reason["matched_day"] = matched_day
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="activity_completed",
        session=session,
        before_snapshot=before,
        reason=reason,
    )
    return PlanSessionActionResult(action_type="activity_completed", source=source, session=session, event_id=_event_id(event))


def mark_day_completed_for_user(
    db: Session,
    *,
    plan_id: int,
    day: str,
    source: str,
    user_id: int | None = None,
) -> bool:
    return False


def _record_session_action(
    db: Session,
    *,
    user: s.User,
    source: str,
    command_type: str,
    session: s.ScheduledSession,
    before_snapshot: dict[str, Any],
    reason: dict[str, Any] | None = None,
) -> s.PlanMutationEventRecord:
    return repo.add_plan_mutation_event(
        db,
        user_id=user.id,
        source=source,
        trigger_type="session_action",
        command_type=command_type,
        target_session_ids=[session.id],
        before_snapshot=before_snapshot,
        after_snapshot=_session_snapshot(session),
        reason=reason or {},
        impact={},
        user_visible_summary="",
        explained_to_user=False,
        conversation_turn_id=None,
    )


def _decision_session_ids(decision: MutationDecision) -> list[int]:
    ids = []
    if decision.target_session_id is not None:
        ids.append(int(decision.target_session_id))
    if decision.second_session_id is not None:
        ids.append(int(decision.second_session_id))
    return ids


def _scheduled_session_by_id(scheduled_sessions: Sequence[Any], session_id: int | None) -> Any | None:
    if session_id is None:
        return None
    for session in scheduled_sessions:
        if getattr(session, "id", None) == session_id:
            return session
    return None


def _session_snapshot(session: s.ScheduledSession | None) -> dict[str, Any]:
    if session is None:
        return {}
    scheduled_date = getattr(session, "scheduled_date", None)
    return {
        "id": getattr(session, "id", None),
        "day": getattr(session, "day", None),
        "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
        "sport_type": getattr(session, "sport_type", None),
        "session_type": getattr(session, "session_type", None),
        "session_title": getattr(session, "session_title", None),
        "duration_min": getattr(session, "duration_min", None),
        "completion_status": getattr(session, "completion_status", None),
    }


def _jsonable_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_dict"):
        return dict(value.as_dict())
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {"value": str(value)}


def _event_id(event: Any) -> int | None:
    value = getattr(event, "id", None)
    return int(value) if value is not None else None


def _build_user_visible_summary(
    decision: MutationDecision,
    updated_session: Any,
    second_updated_session: Any | None = None,
) -> str:
    if decision.mutation_type != "replace_session":
        committed_summary = _build_committed_mutation_summary(
            decision=decision,
            updated_session=updated_session,
            second_updated_session=second_updated_session,
        )
        return committed_summary or decision.fitmas_message
    title = str(_value(updated_session, "session_title") or decision.new_title or "seance adaptee").strip()
    duration_min = _value(updated_session, "duration_min") or decision.new_duration_min
    intensity = str(_value(updated_session, "intensity") or decision.new_intensity or "").strip().lower()
    parts = [f"OK. Je bascule sur {title.lower()}."]
    detail_bits: list[str] = []
    if duration_min:
        detail_bits.append(f"{int(duration_min)} min")
    intensity_labels = {
        "easy": "facile",
        "moderate": "controle",
        "hard": "soutenu",
    }
    if intensity in intensity_labels:
        detail_bits.append(intensity_labels[intensity])
    if detail_bits:
        parts.append(f"{', '.join(detail_bits).capitalize()}.")
    if decision.rationale:
        parts.append(decision.rationale)
    return " ".join(parts)


def _build_committed_mutation_summary(
    *,
    decision: MutationDecision,
    updated_session: Any,
    second_updated_session: Any | None = None,
) -> str:
    if decision.mutation_type == "swap_sessions":
        parts = [
            _build_committed_session_summary(updated_session),
            _build_committed_session_summary(second_updated_session),
        ]
        return " ".join(part for part in parts if part)
    return _build_committed_session_summary(updated_session)


def _build_committed_session_summary(updated_session: Any) -> str:
    if updated_session is None:
        return ""
    title = str(_value(updated_session, "session_title") or "").strip()
    day_label = str(_value(updated_session, "label") or _value(updated_session, "day") or "").strip()
    duration_min = _value(updated_session, "duration_min")
    if day_label and title:
        parts = [f"{day_label}: {title}."]
    elif title:
        parts = [f"{title}."]
    elif day_label:
        parts = [f"{day_label}: seance ajustee."]
    else:
        parts = ["Seance ajustee."]
    if duration_min:
        parts.append(f"{int(duration_min)} min.")
    return " ".join(parts)


def _build_create_session_summary(
    operation: PlanPatchOperation,
    session: Any,
    *,
    coach_message: str,
) -> str:
    if coach_message:
        return coach_message
    title = str(_value(session, "session_title") or operation.new_title or "seance ajoutee").strip()
    duration_min = _value(session, "duration_min") or operation.new_duration_min
    parts = [f"OK. J'ajoute {title.lower()}."]
    if duration_min:
        parts.append(f"{int(duration_min)} min.")
    return " ".join(parts)


def _parse_target_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    try:
        return date.fromisoformat(str(raw_value)[:10])
    except ValueError:
        return None


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
