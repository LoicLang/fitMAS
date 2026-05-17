from __future__ import annotations

from datetime import date
from typing import Literal

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.plan_mutation_service import PlanPatchServiceResult


PlanPatchReplyMode = Literal["applied", "pending", "blocked", "clarification"]


def plan_patch_service_result_to_outcome(
    service_result: PlanPatchServiceResult | None,
    *,
    mode: PlanPatchReplyMode,
) -> DecisionOutcome:
    kind = _kind(mode)
    return DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=_applied_commands(service_result) if kind == "plan_committed" else (),
        candidates=_candidate_summaries(service_result, kind=kind),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=_label(kind),
            reason_summary=_reason_summary(service_result, mode=mode),
            evidence=_candidate_summaries(service_result, kind=kind),
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


def _kind(mode: PlanPatchReplyMode):
    return {
        "applied": "plan_committed",
        "pending": "plan_pending",
        "blocked": "plan_blocked",
        "clarification": "clarification",
    }[mode]


def _applied_commands(service_result: PlanPatchServiceResult | None) -> tuple[CommandResult, ...]:
    mutation_result = getattr(service_result, "mutation_result", None)
    events = tuple(getattr(mutation_result, "applied_events", ()) or ())
    results: list[CommandResult] = []
    for index, event in enumerate(events, start=1):
        summary = str(getattr(event, "user_visible_summary", "") or "").strip()
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


def _reason_summary(service_result: PlanPatchServiceResult | None, *, mode: PlanPatchReplyMode) -> str:
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


def _candidate_summaries(service_result: PlanPatchServiceResult | None, *, kind: str) -> tuple[str, ...]:
    if kind == "plan_committed":
        return (*_operation_summaries(service_result), *_applied_event_facts(service_result))
    return _operation_summaries(service_result)


def _operation_summaries(service_result: PlanPatchServiceResult | None) -> tuple[str, ...]:
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


def _applied_event_facts(service_result: PlanPatchServiceResult | None) -> tuple[str, ...]:
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


def _label(kind: str) -> str:
    return {
        "plan_committed": "Adaptation appliquee",
        "plan_pending": "Adaptation a confirmer",
        "plan_blocked": "Adaptation bloquee",
        "clarification": "Clarification requise",
    }[kind]
