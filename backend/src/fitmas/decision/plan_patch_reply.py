from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fitmas import coach_voice
from fitmas import repository as repo
from fitmas.decision import DecisionReplyComposer
from fitmas.decision.planning_outcomes import plan_patch_service_result_to_outcome
from fitmas.decision.turn_recording import decision_reply_text_for_turn
from fitmas.domain.planning.patch_mutation_service import PlanPatchServiceResult
from fitmas.grounding_contract import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.llm.reply_decision_backend import LLMReplyBackend
from fitmas.plan_patch import PlanPatch

import fitmas.llm.reply_backend as final_reply


logger = logging.getLogger(__name__)


def _mutation_was_applied(service_result) -> bool:
    if service_result is None:
        return False
    return int(getattr(service_result, "applied_count", 0) or 0) > 0 and int(
        getattr(service_result, "event_count", 0) or 0
    ) > 0


def _patch_was_applied(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None or service_result.mutation_result is None:
        return False
    return _mutation_was_applied(service_result.mutation_result)


def _applied_patch_summary(service_result: PlanPatchServiceResult | None, *, fallback: str) -> str:
    if service_result is None or service_result.mutation_result is None:
        return fallback
    summaries: list[str] = []
    for event in service_result.mutation_result.applied_events:
        summary = str(event.user_visible_summary or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    return " ".join(summaries) if summaries else fallback


def _applied_plan_patch_reply(service_result: PlanPatchServiceResult | None, *, fallback: str) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    if reply_result.text and _post_event_reply_matches_plan_patch_result(reply_result.text, service_result):
        return reply_result.text
    committed = " ".join(str(result.payload.get("summary") or "") for result in outcome.applied_commands).strip()
    return committed or fallback


def _post_event_reply_matches_plan_patch_result(
    reply: str,
    service_result: PlanPatchServiceResult | None,
) -> bool:
    if service_result is None or service_result.mutation_result is None:
        return True
    for event in service_result.mutation_result.applied_events:
        if not _post_event_reply_matches_applied_event(reply, event):
            return False
    return True


def _post_event_reply_matches_applied_event(reply: str, event: Any) -> bool:
    if str(getattr(event, "command_type", "") or "") != "move_session":
        return True
    before = _snapshot_date_parts(getattr(event, "before_snapshot", None) or {})
    after = _snapshot_date_parts(getattr(event, "after_snapshot", None) or {})
    if before is None or after is None or before[0] == after[0]:
        return True
    before_iso, before_day = before
    return not (
        _reply_claims_move_destination(reply, before_day)
        or _reply_claims_move_destination(reply, before_iso)
    )


def _snapshot_date_parts(snapshot: dict[str, Any]) -> tuple[str, str] | None:
    raw = str(snapshot.get("scheduled_date") or snapshot.get("day") or "").strip()
    if len(raw) < 10:
        return None
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return parsed.isoformat(), days[parsed.weekday()]


def _reply_claims_move_destination(reply: str, destination: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(reply)
    target = coach_voice.normalize_for_voice_guard(destination)
    movement = r"(passe|deplace|deplacee|deplacees|cale|calee|calees|bouge|reprogramme|avance|repousse)"
    preposition = r"(a|au|aux|vers|pour|le|la)"
    return bool(
        re.search(
            rf"\b{movement}\b[^.?!]{{0,100}}\b{preposition}\s+{re.escape(target)}\b",
            normalized,
        )
    )


def _applied_event_fact(event: Any) -> str:
    target = event.target_session_id if event.target_session_id is not None else "unknown"
    before = _compact_session_snapshot(getattr(event, "before_snapshot", None) or {})
    after = _compact_session_snapshot(getattr(event, "after_snapshot", None) or {})
    if before or after:
        return f"session change: command={event.command_type} target_session_id={target} before={before or 'unknown'} after={after or 'unknown'}"
    return f"commit command={event.command_type} target_session_id={target}"


def _compact_session_snapshot(snapshot: dict[str, Any]) -> str:
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


def _final_reply_context_for_plan_patch_block(
    service_result: PlanPatchServiceResult | None,
) -> final_reply.FinalReplyContext:
    blocked_events: list[final_reply.BlockedEvent] = []
    if service_result is not None:
        if service_result.week_policy_status == "blocked" and service_result.week_review is not None:
            finding = next(
                (item for item in service_result.week_review.findings if item.severity == "blocked"),
                None,
            )
            blocked_events.append(
                final_reply.BlockedEvent(
                    command="plan_patch",
                    reason=finding.code if finding is not None else "week_coherence_blocked",
                    warning=finding.detail if finding is not None else service_result.week_review.summary,
                    suggested_fix=_week_review_suggested_fix(service_result),
                )
            )
        for result in service_result.validation.operation_results:
            if result.status == "valid":
                continue
            warning = result.warning_messages[0] if result.warning_messages else None
            blocked_events.append(
                final_reply.BlockedEvent(
                    command=str(result.operation_type or "plan_patch"),
                    reason=result.block_reason,
                    suggested_fix=result.suggested_fix,
                    warning=warning,
                )
            )
    if not blocked_events:
        blocked_events.append(
            final_reply.BlockedEvent(
                command="plan_patch",
                reason="invalid_plan_patch" if service_result is not None else "composer_context_missing",
            )
        )
    return final_reply.FinalReplyContext(
        blocked_events=tuple(blocked_events),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )


def _blocked_plan_patch_reply(service_result: PlanPatchServiceResult | None) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="blocked")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    return reply_result.text or outcome.explanation.reason_summary


def _execution_applied_patch_blocked_reply(
    db: Session,
    *,
    user,
    action_result: dict,
    service_result: PlanPatchServiceResult | None,
) -> str:
    context = _final_reply_context_for_execution_applied_patch_block(
        db,
        user=user,
        action_result=action_result,
        service_result=service_result,
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    execution_phrase = context.execution_actions_applied[0] if context.execution_actions_applied else "Execution notee."
    return f"{execution_phrase} {final_reply.outage_fallback_reply(context)}"


def _final_reply_context_for_execution_applied_patch_block(
    db: Session,
    *,
    user,
    action_result: dict,
    service_result: PlanPatchServiceResult | None,
) -> final_reply.FinalReplyContext:
    session_ids = tuple(action_result.get("execution_updated_session_ids") or ())
    session = repo.get_scheduled_session(db, user.id, int(session_ids[0])) if session_ids else None
    if session is not None:
        title = str(session.session_title or "La seance").strip()
        status = str(session.completion_status or "").strip()
        execution_phrase = f"{title} notee comme faite." if status == "done" else f"{title} notee comme non faite."
    else:
        execution_phrase = "Execution notee."
    block_context = _final_reply_context_for_plan_patch_block(service_result)
    return final_reply.FinalReplyContext(
        blocked_events=block_context.blocked_events,
        execution_actions_applied=(execution_phrase,),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
        extra_facts=(
            "Une mise a jour d'execution a ete appliquee, mais le changement planning associe a ete bloque.",
        ),
    )


def _plan_patch_needs_confirmation(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None:
        return False
    return (
        service_result.week_policy_status == "requires_confirmation"
        or service_result.validation.status in {"warning", "requires_confirmation"}
    )


def _plan_patch_service_result_requires_clarification(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None:
        return False
    clarification_warning_codes = {
        "ambiguous_target_reference",
    }
    for result in service_result.validation.operation_results:
        if clarification_warning_codes.intersection(result.warning_codes):
            return True
    return False


def _build_plan_patch_clarification_prompt(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> str:
    summary = _plan_patch_clarification_summary(service_result)
    context = final_reply.FinalReplyContext(
        original_llm_reply=summary,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="needs_clarification",
        extra_facts=(
            *render_grounding_packet_for_prompt(grounding),
            f"Clarification requise: {summary}",
            "Aucun changement planning n'a ete commit.",
            "Ne cree pas de pending confirmation.",
        ),
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return "Je dois identifier quelle séance tu veux bouger avant de toucher la semaine."


def _plan_patch_clarification_summary(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "Il manque la cible exacte du changement."
    for result in service_result.validation.operation_results:
        if "ambiguous_target_reference" in result.warning_codes:
            if result.warning_messages:
                return _safe_user_visible_pending_text(result.warning_messages[0])
            return "Plusieurs séances peuvent correspondre à cette demande."
    return "Il manque la cible exacte du changement."


def _plan_patch_confirmation_summary(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "Changement a confirmer avant de bouger la semaine."
    if service_result.week_policy_status == "requires_confirmation" and service_result.week_review is not None:
        summary = str(service_result.week_review.summary or "").strip()
        if summary:
            return _safe_user_visible_pending_text(summary)
    first = service_result.validation.operation_results[0] if service_result.validation.operation_results else None
    if first is not None:
        if first.warning_messages:
            return _safe_user_visible_pending_text(first.warning_messages[0])
        if first.block_reason:
            return _safe_user_visible_pending_text(first.block_reason)
    return "Ce changement modifie sensiblement la semaine."


def _plan_patch_pending_summary(
    service_result: PlanPatchServiceResult | None,
    *,
    patch: PlanPatch | None = None,
) -> str:
    if service_result is not None and service_result.week_policy_status == "requires_confirmation":
        return _plan_patch_confirmation_summary(service_result)
    for candidate in (
        getattr(patch, "confirmation_reason", None),
        getattr(patch, "coach_message", None),
    ):
        value = str(candidate or "").strip()
        if value and not coach_voice.message_has_user_facing_internal_jargon(value):
            return value
    return _plan_patch_confirmation_summary(service_result)


def _plan_patch_pending_reason(
    service_result: PlanPatchServiceResult | None,
    *,
    fallback_reason: str | None,
) -> str:
    fallback = str(fallback_reason or "").strip()
    if fallback and not coach_voice.message_has_user_facing_internal_jargon(fallback):
        return fallback
    return _plan_patch_confirmation_summary(service_result)


def _safe_user_visible_pending_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value or coach_voice.message_has_user_facing_internal_jargon(value):
        return "Changement a confirmer avant de bouger la semaine."
    return value


safe_user_visible_pending_text = _safe_user_visible_pending_text


def _plan_patch_confirmation_reply_requests_clarification(reply_text: str | None) -> bool:
    if not reply_text:
        return False
    normalized = coach_voice.normalize_for_voice_guard(str(reply_text))
    clarification_markers = (
        "tu parlais de",
        "tu peux me preciser",
        "tu peux me dire si",
        "preciser laquelle",
        "preciser lesquelles",
        "tu pensais a quel",
        "tu veux dire quel",
        "tu visais",
        "si tu visais",
        "plusieurs seances",
        "quel sport",
        "quelle seance",
        "quel jour",
        "quel creneau",
        "laquelle tu visais",
        "lequel tu visais",
        "laquelle tu veux",
        "lequel tu veux",
        "dit laquelle",
        "dis moi laquelle",
    )
    if any(marker in normalized for marker in clarification_markers):
        return True
    if "?" not in str(reply_text):
        return False
    return bool(re.search(r"\b(quel|quelle|quels|quelles|lequel|laquelle|lesquelles)\b", normalized))


def _week_review_suggested_fix(service_result: PlanPatchServiceResult) -> str | None:
    review = service_result.week_review
    if review is None:
        return None
    for adjustment in review.suggested_adjustments:
        reason = str(adjustment.get("reason") or "").strip()
        if reason:
            return reason
    return None


def _build_plan_patch_confirmation_prompt(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="pending")
    reply_result = _decision_reply_composer().compose(
        outcome,
        context=None,
        grounding_facts=render_grounding_packet_for_prompt(grounding),
    )
    reply_text = reply_result.text
    fallback = f"{outcome.explanation.reason_summary} Tu confirmes ?"
    if not reply_text:
        return fallback
    if _plan_patch_confirmation_reply_requests_clarification(reply_text):
        return reply_text
    if grounding is None:
        return reply_text

    verified_factual = final_reply.verify_factual_reply(
        reply_text,
        grounding=_plan_patch_confirmation_grounding(
            grounding=grounding,
            service_result=service_result,
        ),
        pipeline_capability="plan_patch_confirmation",
    )
    if not verified_factual:
        return fallback
    rechecked = final_reply.verify_uncommitted_reply(
        verified_factual,
        final_reply.FinalReplyContext(
            pending_summary=outcome.explanation.reason_summary,
            allowed_to_claim_mutation=False,
            pipeline="conversation",
            pipeline_capability="plan_patch_confirmation",
            extra_facts=_plan_patch_confirmation_facts(service_result, grounding=grounding),
        ),
    )
    return rechecked or fallback


def _plan_patch_confirmation_facts(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> tuple[str, ...]:
    patch = service_result.patch if service_result is not None else None
    if patch is None:
        return render_grounding_packet_for_prompt(grounding)
    facts: list[str] = []
    facts.extend(render_grounding_packet_for_prompt(grounding))
    coach_message = str(patch.coach_message or "").strip()
    if coach_message:
        facts.append(f"Patch coach_message: {coach_message}")
    for index, operation in enumerate(patch.operations, start=1):
        bits = [f"operation#{index}", str(operation.operation_type)]
        if operation.target_session_id is not None:
            bits.append(f"target_session_id={operation.target_session_id}")
        if operation.second_session_id is not None:
            bits.append(f"second_session_id={operation.second_session_id}")
        if operation.target_date:
            bits.append(f"target_date={operation.target_date}")
        if operation.new_sport_type:
            bits.append(f"new_sport_type={operation.new_sport_type}")
        if operation.new_session_type:
            bits.append(f"new_session_type={operation.new_session_type}")
        if operation.new_title:
            bits.append(f"new_title={operation.new_title}")
        if operation.new_duration_min is not None:
            bits.append(f"new_duration_min={operation.new_duration_min}")
        if operation.new_intensity:
            bits.append(f"new_intensity={operation.new_intensity}")
        if operation.rationale:
            bits.append(f"rationale={operation.rationale}")
        facts.append(" | ".join(bits))
    return tuple(facts)


def _plan_patch_confirmation_grounding(
    *,
    grounding: ReplyGroundingPacket,
    service_result: PlanPatchServiceResult | None,
) -> ReplyGroundingPacket:
    patch_facts = _plan_patch_confirmation_facts(service_result, grounding=None)
    if not patch_facts:
        return grounding
    return ReplyGroundingPacket(
        local_date=grounding.local_date,
        timezone_name=grounding.timezone_name,
        temporal_references=grounding.temporal_references,
        plan_window=grounding.plan_window,
        extra_facts=tuple(grounding.extra_facts) + patch_facts,
    )


def _log_plan_patch_blocked(service_result: PlanPatchServiceResult | None, *, user_id: int | None) -> None:
    if service_result is None:
        return
    for result in service_result.validation.operation_results:
        if result.status == "valid":
            continue
        logger.warning(
            "plan_patch_blocked user=%s operation=%s status=%s reason=%s target=%s warnings=%s",
            user_id,
            result.operation_type,
            result.status,
            result.block_reason,
            result.target_session_id,
            list(result.warning_codes),
        )


def _blocked_mutation_reply(decision, service_result=None) -> str:
    block_reason: str | None = None
    warning_hint: str | None = None
    if service_result is not None:
        blocked = getattr(service_result, "blocked_events", ()) or ()
        decision_target = getattr(decision, "target_session_id", None)
        matching = next(
            (
                event for event in blocked
                if event.command_type == getattr(decision, "mutation_type", "")
                and (decision_target is None or event.target_session_id == decision_target)
            ),
            None,
        )
        if matching is None and blocked:
            matching = blocked[0]
        if matching is not None:
            block_reason = matching.block_reason
            warnings = matching.warnings or ()
            warning_hint = warnings[0] if warnings else None

    context = final_reply.FinalReplyContext(
        original_llm_reply=decision_reply_text_for_turn(decision),
        blocked_events=(
            final_reply.BlockedEvent(
                command=str(getattr(decision, "mutation_type", "") or "mutation"),
                reason=block_reason,
                warning=warning_hint,
            ),
        ) if block_reason or warning_hint else (
            final_reply.BlockedEvent(
                command=str(getattr(decision, "mutation_type", "") or "mutation"),
                reason="mutation_not_validated",
            ),
        ),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return final_reply.outage_fallback_reply(context)


def _decision_reply_composer() -> DecisionReplyComposer:
    return DecisionReplyComposer(reply_backend=LLMReplyBackend())
