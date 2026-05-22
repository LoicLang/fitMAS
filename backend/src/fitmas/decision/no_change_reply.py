from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas.decision.grounding import ReplyGroundingPacket
from fitmas.domain.coaching import coach_voice
from fitmas.domain.planning import repository as planning_repo
import fitmas.llm.reply_backend as final_reply


def memory_action_phrases_for_final_reply(action_result: dict) -> tuple[str, ...]:
    if int(action_result.get("memory_applied") or 0) <= 0:
        return ()
    return ("Memoire utilisateur mise a jour.",)


def execution_action_phrases_for_final_reply(
    db: Session,
    *,
    user,
    action_result: dict,
) -> tuple[str, ...]:
    phrases: list[str] = []
    for raw_session_id in tuple(action_result.get("execution_updated_session_ids") or ()):
        try:
            session_id = int(raw_session_id)
        except (TypeError, ValueError):
            continue
        session = planning_repo.get_scheduled_session(db, user.id, session_id)
        if session is None:
            continue
        title = str(session.session_title or "La seance").strip()
        scheduled_date = getattr(session, "scheduled_date", None)
        if scheduled_date is not None and hasattr(scheduled_date, "date"):
            scheduled_date = scheduled_date.date()
        date_hint = f" du {scheduled_date.isoformat()}" if scheduled_date is not None and hasattr(scheduled_date, "isoformat") else ""
        status = str(session.completion_status or "").strip()
        if status == "done":
            phrases.append(f"{title}{date_hint} notee comme faite.")
        elif status == "skipped":
            phrases.append(f"{title}{date_hint} notee comme non faite.")
        else:
            phrases.append(f"{title}{date_hint} mise a jour.")
    if not phrases and int(action_result.get("execution_applied") or 0) > 0:
        phrases.append("Execution notee.")
    return tuple(phrases)


def compose_no_change_reply_for_turn(
    *,
    db: Session,
    user,
    user_text: str,
    original_reply: str,
    turn_context: dict[str, object],
    grounding: ReplyGroundingPacket | None = None,
    action_result: dict | None = None,
) -> tuple[str, str | None]:
    action_result = action_result or {}
    memory_actions_applied = memory_action_phrases_for_final_reply(action_result)
    execution_actions_applied = execution_action_phrases_for_final_reply(
        db,
        user=user,
        action_result=action_result,
    )
    primary_intent = turn_context_primary_intent(turn_context)
    plan_lookup_capability = primary_intent == "plan_lookup" or (
        turn_context_requires_truth_read(turn_context)
        and primary_intent not in {"plan_mutation", "availability_constraint", "health_signal", "execution_report"}
    )
    capability = (
        "plan_lookup"
        if plan_lookup_capability
        else "execution_report"
        if primary_intent == "execution_report"
        else "no_change"
    )
    if capability == "plan_lookup":
        lookup_grounding = grounding if turn_context_should_ground_plan_lookup(turn_context) else None
        composed_reply = final_reply.compose_plan_lookup_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
            grounding=lookup_grounding,
        )
    elif capability == "execution_report":
        composed_reply = final_reply.compose_execution_report_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
        )
    else:
        composed_reply = final_reply.compose_no_change_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
        )
    if not composed_reply:
        if not _is_safe_original_reply(original_reply):
            fallback = _safe_no_change_fallback(
                capability=capability,
                execution_actions_applied=execution_actions_applied,
            )
            turn_context["final_reply"] = {
                "capability": capability,
                "draft": original_reply,
                "output": fallback,
                "source": "canonical_safe_reply",
                "composed": False,
            }
            return fallback, "canonical_no_action_safe_reply"
        turn_context["final_reply"] = {
            "capability": capability,
            "draft": original_reply,
            "output": original_reply,
            "source": "draft_fallback",
            "composed": False,
        }
        return original_reply, None
    turn_context["final_reply"] = {
        "capability": capability,
        "draft": original_reply,
        "output": composed_reply,
        "source": "composer",
        "composed": True,
    }
    turn_context["final_reply_composed"] = True
    turn_context["final_reply_capability"] = capability
    return composed_reply, f"{capability}_composed"


def turn_context_primary_intent(turn_context: dict[str, object]) -> str:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return ""
    return str(turn_plan.get("primary_intent") or "")


def turn_context_requires_truth_read(turn_context: dict[str, object]) -> bool:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return False
    return bool(turn_plan.get("requires_truth_read")) or str(turn_plan.get("truth_scope") or "") == "plan_window"


def turn_context_should_ground_plan_lookup(turn_context: dict[str, object]) -> bool:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return False
    if str(turn_plan.get("truth_scope") or "") == "plan_window":
        return True
    refs = turn_plan.get("temporal_references")
    return isinstance(refs, list) and bool(refs)


def _is_safe_original_reply(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if coach_voice.message_violates_coach_voice(value):
        return False
    if coach_voice.message_has_user_facing_internal_jargon(value):
        return False
    if coach_voice.message_looks_receipt_style(value):
        return False
    return True


def _safe_no_change_fallback(
    *,
    capability: str = "no_change",
    execution_actions_applied: tuple[str, ...] = (),
) -> str:
    if capability == "execution_report" and execution_actions_applied:
        return f"{execution_actions_applied[0]} Le reste du planning ne bouge pas."
    return "Je le prends en compte. Le planning ne bouge pas pour l'instant."
