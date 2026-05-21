from __future__ import annotations

from datetime import date
from typing import Any, Callable, Literal

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.patch_summary import summarize_plan_patch_for_user
from fitmas.models import Extraction


PlanPatchReplyMode = Literal["applied", "pending", "blocked", "clarification"]


def canonical_planning_blocked_outcome(
    *,
    reason: str,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    decision_reply_composer_fn: Callable[[], Any],
) -> ConversationTurnOutcome:
    reason_summary = f"Je bloque ce changement pour l'instant: {reason}."
    decision_outcome = DecisionOutcome(
        kind="plan_blocked",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Changement planning bloque",
            reason_summary=reason_summary,
            evidence=("planning_runtime_cutover", reason),
            tradeoff=None,
            impact={},
            protected=("runtime_single_path", "no_legacy_fallthrough"),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_planning_blocked",
            audience="conversation",
            allowed_claims=("plan_blocked",),
            forbidden_claims=("plan_committed", "plan_committed_without_event", "execution_updated_without_event"),
        ),
    )
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_result.text or reason_summary,
        response_mode="canonical_planning_blocked",
        mutation_applied=False,
        pending_confirmation=False,
    )


def legacy_decision_contract_disabled_outcome(
    *,
    decision_artifact: Any | None = None,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    decision_reply_composer_fn: Callable[[], Any],
) -> ConversationTurnOutcome:
    reason_summary = (
        "Je ne peux pas appliquer cette ancienne forme de decision. "
        "Redis-moi le changement voulu et je le reevalue proprement."
    )
    decision_outcome = DecisionOutcome(
        kind="plan_blocked",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Decision non appliquee",
            reason_summary=reason_summary,
            evidence=("legacy_contract_disabled",),
            tradeoff=None,
            impact={},
            protected=("single_planning_runtime", "no_legacy_write"),
            next_step="Redis-moi le changement voulu.",
        ),
        reply_contract=ReplyContract(
            mode="legacy_contract_disabled",
            audience="conversation",
            allowed_claims=("plan_blocked",),
            forbidden_claims=("plan_committed", "plan_committed_without_event", "execution_updated_without_event"),
        ),
    )
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_result.text or reason_summary,
        response_mode="legacy_decision_contract_disabled",
        decision=decision_artifact,
        mutation_applied=False,
        pending_confirmation=False,
    )


def conversation_outcome_from_planning_runtime_result(
    result,
    *,
    db=None,
    user=None,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    original_reply: str = "",
    turn_context: dict[str, object] | None = None,
    action_result: dict | None = None,
    decision_reply_composer_fn: Callable[[], Any],
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None = None,
) -> ConversationTurnOutcome:
    action_result = action_result or {}
    if (
        result.kind == "block"
        and db is not None
        and user is not None
        and int(action_result.get("execution_applied") or 0) > 0
        and compose_no_change_reply_for_turn_fn is not None
    ):
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=original_reply or result.reason,
            turn_context=turn_context or {},
            grounding=None,
            action_result=action_result,
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode=composed_mode or "planning_runtime_block_with_execution_update",
            mutation_applied=False,
            pending_confirmation=False,
        )
    decision_outcome = planning_decision_to_outcome(result)
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    reply_text = reply_result.text or decision_outcome.explanation.reason_summary
    pending = decision_outcome.kind in {"plan_pending", "plan_choice_pending"}
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_text,
        response_mode=planning_runtime_response_mode_for_outcome_kind(decision_outcome.kind),
        mutation_applied=decision_outcome.kind == "plan_committed",
        pending_confirmation=pending,
        pending_confirmation_id=getattr(result, "pending_confirmation_id", None),
    )


def planning_runtime_response_mode(kind: str) -> str:
    return {
        "commit": "planning_runtime_commit",
        "pending_confirmation": "planning_runtime_pending_confirmation",
        "pending_choice": "planning_runtime_pending_choice",
        "block": "planning_runtime_block",
    }.get(kind, f"planning_runtime_{kind}")


def planning_runtime_response_mode_for_outcome_kind(kind: str) -> str:
    return {
        "plan_committed": "planning_runtime_commit",
        "plan_pending": "planning_runtime_pending_confirmation",
        "plan_choice_pending": "planning_runtime_pending_choice",
        "plan_blocked": "planning_runtime_block",
    }.get(kind, f"planning_runtime_{kind}")


def planning_decision_to_outcome(decision: PlanningDecisionResult) -> DecisionOutcome:
    kind = _outcome_kind(decision)
    return DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=_command_results(decision),
        candidates=_candidate_summaries(decision),
        selected_candidate_id=decision.selected_candidate_id,
        explanation=DecisionExplanation(
            decision_label=_decision_label(kind),
            reason_summary=decision.reason,
            evidence=_planning_evidence(decision),
            tradeoff=None,
            impact=_impact(decision),
            protected=_protected(kind),
            next_step=_next_step(kind),
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",)
            if kind == "plan_committed"
            else ("pending_created",)
            if "pending" in kind
            else (),
            forbidden_claims=() if kind == "plan_committed" else ("plan_committed",),
        ),
    )


def plan_patch_service_result_to_outcome(
    service_result: Any | None,
    *,
    mode: PlanPatchReplyMode,
) -> DecisionOutcome:
    kind = _plan_patch_kind(mode)
    return DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=_applied_commands(service_result) if kind == "plan_committed" else (),
        candidates=_plan_patch_candidate_summaries(service_result, kind=kind),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=_plan_patch_label(kind),
            reason_summary=_reason_summary(service_result, mode=mode),
            evidence=_plan_patch_candidate_summaries(service_result, kind=kind),
            tradeoff=None,
            impact={},
            protected=("verite planning",) if kind == "plan_committed" else ("coherence semaine",),
            next_step="Tu confirmes ?" if kind == "plan_pending" else None,
        ),
        reply_contract=ReplyContract(
            mode=f"legacy_plan_patch_{mode}",
            audience="telegram",
            allowed_claims=("plan_committed",)
            if kind == "plan_committed"
            else ("pending_created",)
            if kind == "plan_pending"
            else (),
            forbidden_claims=() if kind == "plan_committed" else ("plan_committed",),
        ),
    )


def _outcome_kind(decision: PlanningDecisionResult):
    if decision.kind == "commit":
        return "plan_committed" if _has_commit_evidence(decision) else "plan_blocked"
    if decision.kind == "pending_confirmation":
        return "plan_pending" if _has_pending_evidence(decision) else "plan_blocked"
    if decision.kind == "pending_choice":
        return "plan_choice_pending" if _has_pending_evidence(decision) else "plan_blocked"
    return "plan_blocked"


def _command_results(decision: PlanningDecisionResult) -> tuple[CommandResult, ...]:
    result = decision.command_result
    if result is None or not _has_commit_evidence(decision):
        return ()
    return (
        CommandResult(
            command_id=f"planning:{decision.selected_candidate_id or 'selected'}",
            domain="planning",
            name="plan_change",
            status="applied",
            event_id=str(result.payload.get("event_id") or "planning_event"),
            payload=result.payload,
        ),
    )


def _candidate_summaries(decision: PlanningDecisionResult) -> tuple[str, ...]:
    summaries: list[str] = []
    summaries.extend(_selected_patch_operation_summaries(decision))
    for evaluated in decision.evaluated_candidates:
        candidate = getattr(evaluated, "candidate", None)
        rationale = str(getattr(candidate, "rationale", "") or "").strip()
        if rationale:
            summaries.append(rationale)
    return tuple(summaries or decision.candidate_options)


def _selected_patch_operation_summaries(decision: PlanningDecisionResult) -> tuple[str, ...]:
    patch = getattr(decision, "selected_patch", None)
    if patch is None:
        return ()
    user_summary = summarize_plan_patch_for_user(patch)
    if user_summary:
        return (user_summary,)
    summaries: list[str] = []
    for operation in tuple(getattr(patch, "operations", ()) or ()):
        bits = [str(getattr(operation, "operation_type", "") or "").strip()]
        target_session_id = getattr(operation, "target_session_id", None)
        if target_session_id is not None:
            bits.append(f"target_session_id={target_session_id}")
        target_date = str(getattr(operation, "target_date", "") or "").strip()
        if target_date:
            bits.append(f"target_date={target_date}")
        new_sport = str(getattr(operation, "new_sport_type", "") or "").strip()
        if new_sport:
            bits.append(f"new_sport_type={new_sport}")
        new_duration = getattr(operation, "new_duration_min", None)
        if new_duration is not None:
            bits.append(f"new_duration_min={new_duration}")
        new_intensity = str(getattr(operation, "new_intensity", "") or "").strip()
        if new_intensity:
            bits.append(f"new_intensity={new_intensity}")
        summaries.append(" | ".join(bit for bit in bits if bit))
    return tuple(summary for summary in summaries if summary)


def _decision_label(kind: str) -> str:
    return {
        "plan_committed": "Adaptation appliquee",
        "plan_pending": "Adaptation a confirmer",
        "plan_choice_pending": "Choix d'adaptation a confirmer",
        "plan_blocked": "Adaptation bloquee",
    }[kind]


def _planning_evidence(decision: PlanningDecisionResult) -> tuple[str, ...]:
    items = [f"policy={decision.kind}"]
    if decision.selected_candidate_id:
        items.append(f"selected_candidate_id={decision.selected_candidate_id}")
    if decision.pending_confirmation_id is not None:
        items.append(f"pending_confirmation_id={decision.pending_confirmation_id}")
    if decision.kind == "commit" and not _has_commit_evidence(decision):
        items.append("missing_commit_event")
    if decision.kind in {"pending_confirmation", "pending_choice"} and not _has_pending_evidence(decision):
        items.append("missing_pending_confirmation")
    return tuple(items)


def _impact(decision: PlanningDecisionResult) -> dict[str, Any]:
    payload = dict(getattr(decision.command_result, "payload", {}) or {})
    if decision.pending_confirmation_id is not None:
        payload["pending_confirmation_id"] = decision.pending_confirmation_id
        payload["requires_confirmation"] = True
    payload.update(_selected_patch_impact(decision))
    return payload


def _selected_patch_impact(decision: PlanningDecisionResult) -> dict[str, Any]:
    patch = getattr(decision, "selected_patch", None)
    operations = tuple(getattr(patch, "operations", ()) or ()) if patch is not None else ()
    if not operations:
        return {}
    target_dates = tuple(
        str(getattr(operation, "target_date", "") or "").strip()
        for operation in operations
        if str(getattr(operation, "target_date", "") or "").strip()
    )
    move_count = sum(
        1 for operation in operations if str(getattr(operation, "operation_type", "") or "") == "move_session"
    )
    impact: dict[str, Any] = {
        "operation_count": len(operations),
    }
    if move_count:
        impact["move_session_count"] = move_count
    if target_dates:
        impact["target_dates"] = target_dates
    return impact


def _protected(kind: str) -> tuple[str, ...]:
    if kind == "plan_blocked":
        return ("coherence semaine", "risque sportif")
    if "pending" in kind:
        return ("confirmation utilisateur", "coherence semaine")
    return ("verite planning",)


def _next_step(kind: str) -> str | None:
    if kind == "plan_pending":
        return "Tu confirmes ?"
    if kind == "plan_choice_pending":
        return "Choisis l'option que tu veux garder."
    return None


def _has_commit_evidence(decision: PlanningDecisionResult) -> bool:
    result = decision.command_result
    if result is None:
        return False
    return result.status == "applied" and int(result.event_count or 0) > 0


def _has_pending_evidence(decision: PlanningDecisionResult) -> bool:
    result = decision.command_result
    if result is None:
        return False
    pending_id = decision.pending_confirmation_id or result.pending_confirmation_id
    return result.status == "pending" and pending_id is not None


def _plan_patch_kind(mode: PlanPatchReplyMode):
    return {
        "applied": "plan_committed",
        "pending": "plan_pending",
        "blocked": "plan_blocked",
        "clarification": "clarification",
    }[mode]


def _applied_commands(service_result: Any | None) -> tuple[CommandResult, ...]:
    mutation_result = getattr(service_result, "mutation_result", None)
    events = tuple(getattr(mutation_result, "applied_events", ()) or ())
    results: list[CommandResult] = []
    for index, event in enumerate(events, start=1):
        summary = _event_user_visible_summary(event)
        results.append(
            CommandResult(
                command_id=f"plan_patch:{index}",
                domain="planning",
                name=str(getattr(event, "command_type", "") or "plan_patch"),
                status="applied",
                event_id=str(getattr(event, "id", "") or f"plan_patch_event_{index}"),
                payload={"summary": summary},
            )
        )
    return tuple(results)


def _event_user_visible_summary(event: Any) -> str:
    command = str(getattr(event, "command_type", "") or "").strip()
    before = getattr(event, "before_snapshot", None) or {}
    after = getattr(event, "after_snapshot", None) or {}
    title = str(after.get("session_title") or before.get("session_title") or "la seance").strip()
    before_date = _date_with_day_label(str(before.get("scheduled_date") or before.get("day") or ""))
    after_date = _date_with_day_label(str(after.get("scheduled_date") or after.get("day") or ""))
    if command == "move_session" and after_date:
        if before_date and before_date != after_date:
            return f"J'ai deplace {title} du {before_date} au {after_date}."
        return f"J'ai deplace {title} au {after_date}."
    summary = str(getattr(event, "user_visible_summary", "") or "").strip()
    if summary:
        return summary
    if title and after_date:
        return f"{title}: {after_date}."
    return "Changement planning applique."


def _reason_summary(service_result: Any | None, *, mode: PlanPatchReplyMode) -> str:
    if service_result is None:
        return "Changement planning traite."
    if service_result.week_policy_status == "blocked" and service_result.week_review is not None:
        finding = next(
            (item for item in service_result.week_review.findings if item.severity == "blocked"),
            None,
        )
        if finding is not None and str(finding.detail or "").strip():
            return str(finding.detail).strip()
        summary = str(service_result.week_review.summary or "").strip()
        if summary:
            return summary
    if service_result.week_policy_status == "requires_confirmation" and service_result.week_review is not None:
        summary = str(service_result.week_review.summary or "").strip()
        if summary:
            return summary
    for result in service_result.validation.operation_results:
        if result.suggested_fix:
            return str(result.suggested_fix)
        if result.warning_messages:
            return str(result.warning_messages[0])
        if result.block_reason:
            return str(result.block_reason)
    summary = str(service_result.validation.summary or "").strip()
    if summary:
        return summary
    return "Changement planning traite."


def _plan_patch_candidate_summaries(service_result: Any | None, *, kind: str) -> tuple[str, ...]:
    if kind == "plan_committed":
        return (*_operation_summaries(service_result), *_applied_event_facts(service_result))
    return _operation_summaries(service_result)


def _operation_summaries(service_result: Any | None) -> tuple[str, ...]:
    patch = getattr(service_result, "patch", None)
    if patch is None:
        return ()
    summaries: list[str] = []
    for operation in patch.operations:
        bits = [operation.operation_type]
        if operation.target_session_id is not None:
            bits.append(f"target_session_id={operation.target_session_id}")
        if operation.target_date:
            bits.append(f"target_date={operation.target_date}")
        if operation.new_sport_type:
            bits.append(f"new_sport_type={operation.new_sport_type}")
        summaries.append(" | ".join(bits))
    return tuple(summaries)


def _applied_event_facts(service_result: Any | None) -> tuple[str, ...]:
    mutation_result = getattr(service_result, "mutation_result", None)
    events = tuple(getattr(mutation_result, "applied_events", ()) or ())
    facts: list[str] = []
    for event in events:
        target = getattr(event, "target_session_id", None)
        before = _compact_session_snapshot(getattr(event, "before_snapshot", None) or {})
        after = _compact_session_snapshot(getattr(event, "after_snapshot", None) or {})
        if before or after:
            facts.append(
                f"session change: command={getattr(event, 'command_type', None)} "
                f"target_session_id={target if target is not None else 'unknown'} "
                f"before={before or 'unknown'} after={after or 'unknown'}"
            )
        else:
            facts.append(
                f"commit command={getattr(event, 'command_type', None)} "
                f"target_session_id={target if target is not None else 'unknown'}"
            )
    return tuple(facts)


def _compact_session_snapshot(snapshot: dict) -> str:
    if not snapshot:
        return ""
    title = str(snapshot.get("session_title") or snapshot.get("title") or "").strip()
    scheduled_date = str(snapshot.get("scheduled_date") or snapshot.get("day") or "").strip()
    sport = str(snapshot.get("sport_type") or "").strip()
    duration = snapshot.get("duration_min")
    bits = [bit for bit in (title, _date_with_day_label(scheduled_date), sport) if bit]
    if duration is not None:
        try:
            bits.append(f"{int(duration)} min")
        except (TypeError, ValueError):
            bits.append(f"{duration} min")
    return " | ".join(bits)


def _date_with_day_label(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) < 10:
        return value
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return f"{parsed.isoformat()} ({days[parsed.weekday()]})"


def _plan_patch_label(kind: str) -> str:
    return {
        "plan_committed": "Adaptation appliquee",
        "plan_pending": "Adaptation a confirmer",
        "plan_blocked": "Adaptation bloquee",
        "clarification": "Clarification requise",
    }[kind]
