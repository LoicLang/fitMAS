from __future__ import annotations

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
