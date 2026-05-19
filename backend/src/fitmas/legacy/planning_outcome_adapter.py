from __future__ import annotations

from typing import Any

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.patch_summary import summarize_plan_patch_for_user


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
            evidence=_evidence(decision),
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


def _evidence(decision: PlanningDecisionResult) -> tuple[str, ...]:
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
