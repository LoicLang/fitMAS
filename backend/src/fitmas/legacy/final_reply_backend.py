from __future__ import annotations

import re
from datetime import date

from fitmas import coach_voice
from fitmas.legacy import conversation_reply_adapter as final_reply
from fitmas.decision.reply_request import ReplyRequest
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


class LegacyFinalReplyBackend:
    def __init__(self, *, request_text_fn=None, verifier_text_fn=None):
        self._request_text_fn = request_text_fn or final_reply.request_text
        self._verifier_text_fn = verifier_text_fn or final_reply.request_text

    def compose(self, request: ReplyRequest) -> str | None:
        if request.kind in {"plan_committed", "plan_pending", "plan_choice_pending", "plan_blocked"}:
            return self._compose_plan(request)
        context = self._context_from_request(request)
        return final_reply.compose_final_reply(context, request_text_fn=self._request_text_fn, force=True)

    def _compose_plan(self, request: ReplyRequest) -> str | None:
        if _is_legacy_plan_patch_request(request):
            context = self._context_from_request(request)
            reply = final_reply.compose_final_reply(context)
            if request.kind in {"plan_pending", "plan_choice_pending"}:
                if _reply_requests_clarification(reply):
                    return reply
                return final_reply.verify_uncommitted_reply(
                    reply,
                    context,
                    request_text_fn=self._verifier_text_fn,
                )
            if request.kind == "plan_committed":
                return final_reply.verify_post_event_reply(
                    reply,
                    context,
                    request_text_fn=self._verifier_text_fn,
                )
            return reply

        if request.kind == "plan_committed" and request.committed_events:
            return " ".join(request.committed_events).strip()
        machine_reply = _machine_planning_reply(request)
        if machine_reply is not None:
            return machine_reply

        return self._compose_policy_plan(request)

    def _compose_policy_plan(self, request: ReplyRequest) -> str | None:
        policy_decision = _policy_decision_from_request(request)
        reply = final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=request.user_text,
            committed_events=request.committed_events,
            candidate_summaries=request.candidate_summaries,
            extra_facts=_extra_facts_from_request(request),
            request_text_fn=self._request_text_fn,
            verifier_text_fn=self._verifier_text_fn,
        )
        if reply is not None:
            return reply
        return None

    def _context_from_request(self, request: ReplyRequest) -> final_reply.FinalReplyContext:
        return final_reply.FinalReplyContext(
            user_text=request.user_text,
            committed_events=request.committed_events,
            blocked_events=tuple(
                final_reply.BlockedEvent(command=request.kind, reason=reason)
                for reason in request.blocked_reasons
            ),
            pending_summary=request.pending_summary,
            memory_actions_applied=request.memory_updates,
            execution_actions_applied=request.execution_updates,
            allowed_to_claim_mutation=bool(request.committed_events),
            pipeline="conversation",
            pipeline_capability=request.kind,
            extra_facts=_extra_facts_from_request(request),
        )


def _policy_decision_from_request(request: ReplyRequest) -> AdaptationPolicyDecision:
    action = {
        "plan_committed": "commit",
        "plan_pending": "pending_confirmation",
        "plan_choice_pending": "pending_choice",
        "plan_blocked": "block",
    }[request.kind]
    return AdaptationPolicyDecision(
        action=action,  # type: ignore[arg-type]
        selected_candidate_id=str((request.metadata or {}).get("selected_candidate_id") or "") or None,
        candidate_options=tuple(request.candidate_summaries),
        reason=request.explanation.reason_summary,
        user_facing_reason=request.explanation.reason_summary,
        requires_confirmation_reason=request.pending_summary,
        risk_level="low" if action == "commit" else "medium" if action != "block" else "high",  # type: ignore[arg-type]
    )


def _is_legacy_plan_patch_request(request: ReplyRequest) -> bool:
    return str(request.contract.mode or "").startswith("legacy_plan_patch_")


def _extra_facts_from_request(request: ReplyRequest) -> tuple[str, ...]:
    return (
        *request.grounding_facts,
        *(f"Option evaluee: {summary}" for summary in request.candidate_summaries),
        *(f"Evidence: {item}" for item in request.explanation.evidence),
        f"Decision: {request.explanation.decision_label}",
        f"Raison: {request.explanation.reason_summary}",
    )


def _machine_planning_reply(request: ReplyRequest) -> str | None:
    if request.kind not in {"plan_pending", "plan_choice_pending"}:
        return None
    summary = _first_user_safe_candidate_summary(request)
    if summary is None:
        return None
    if request.kind == "plan_choice_pending":
        return f"Je vois ces options: {summary}. Tu choisis laquelle ?"
    return f"Je te propose: {summary}. Tu confirmes ?"


def _first_user_safe_candidate_summary(request: ReplyRequest) -> str | None:
    for raw in request.candidate_summaries:
        summary = _humanize_candidate_summary(raw)
        if summary:
            return summary
    return None


def _humanize_candidate_summary(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if _looks_internal_candidate_summary(text):
        return _humanize_internal_candidate_summary(text)
    if _looks_user_safe_candidate_summary(text):
        return text
    return None


def _looks_internal_candidate_summary(text: str) -> bool:
    return any(marker in text for marker in ("target_session_id=", "target_date=", "new_sport_type="))


def _looks_user_safe_candidate_summary(text: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(text)
    if any(marker in normalized for marker in ("backend:", "planpatch", "candidate", "target_session_id", "json")):
        return False
    return normalized.startswith(
        (
            "deplacer la seance ciblee au ",
            "deplacer les ",
            "remplacer la seance ciblee par ",
            "alleger la seance ciblee",
        )
    )


def _humanize_internal_candidate_summary(text: str) -> str | None:
    target_date = _field_value(text, "target_date")
    sport = _field_value(text, "new_sport_type")
    duration = _field_value(text, "new_duration_min")
    intensity = _field_value(text, "new_intensity")
    bits: list[str] = []
    if "move_session" in text and target_date:
        bits.append(f"deplacer la seance ciblee au {_date_label(target_date)}")
    elif "replace_session" in text and sport:
        replacement = _sport_label(sport)
        intensity_label = _intensity_label(intensity)
        if intensity_label:
            replacement = f"{replacement} {intensity_label}"
        if duration:
            replacement = f"{replacement}, {duration} min"
        bits.append(f"remplacer la seance ciblee par {replacement}")
    elif "lighten" in text:
        bits.append("alleger la seance ciblee")
    if sport and "replace_session" not in text:
        bits.append(f"sport={_sport_label(sport)}")
    return ", ".join(bits) if bits else None


def _field_value(text: str, field_name: str) -> str | None:
    match = re.search(rf"{re.escape(field_name)}=([^|]+)", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _date_label(raw: str) -> str:
    value = str(raw or "").strip()
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return f"{parsed.isoformat()} ({days[parsed.weekday()]})"


def _sport_label(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return {
        "cycling": "velo",
        "bike": "velo",
        "velo": "velo",
        "vélo": "velo",
        "swimming": "natation",
        "running": "course",
        "strength": "renfo",
        "mobility": "mobilite",
    }.get(value, str(raw or "").strip() or "seance")


def _intensity_label(raw: str | None) -> str | None:
    value = str(raw or "").strip().lower()
    return {
        "easy": "facile",
        "facile": "facile",
        "moderate": "controle",
        "hard": "soutenu",
    }.get(value)


def _reply_requests_clarification(reply_text: str | None) -> bool:
    if not reply_text:
        return False
    text = str(reply_text)
    normalized = coach_voice.normalize_for_voice_guard(text)
    markers = (
        "tu parlais de",
        "tu peux me preciser",
        "tu peux me dire si",
        "preciser laquelle",
        "tu pensais a quel",
        "tu veux dire quel",
        "tu visais",
        "plusieurs seances",
        "quel sport",
        "quelle seance",
        "quel jour",
        "quel creneau",
        "laquelle tu visais",
        "lequel tu visais",
    )
    if any(marker in normalized for marker in markers):
        return True
    return "?" in text and any(word in normalized.split() for word in ("quel", "quelle", "lequel", "laquelle"))
