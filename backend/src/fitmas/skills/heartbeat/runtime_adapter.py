from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Mapping
from uuid import uuid4

from fitmas.app.telegram.delivery import CoachDraft
from fitmas.decision import DecisionExplanation, DecisionOutcome, InputEvent, ReplyContract
from fitmas.decision.output_verifier import DecisionOutputVerifier, OutputVerifier


HeartbeatTrigger = Literal[
    "morning_briefing",
    "pre_session_reminder",
    "weekly_review",
    "signal_check",
]


@dataclass(frozen=True, slots=True)
class HeartbeatRuntimeResult:
    event: InputEvent
    outcome: DecisionOutcome
    draft: CoachDraft | None
    reply_text: str | None
    verifier_reason: str | None = None


def heartbeat_runtime_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER", "")).strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def heartbeat_runtime_verifier_enforced() -> bool:
    return _env_flag("FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE")


def _env_flag(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def build_heartbeat_input_event(
    *,
    user_id: int = 0,
    trigger: HeartbeatTrigger,
    source: Literal["telegram", "scheduler", "ops"] = "scheduler",
    delivery_channel: Literal["telegram", "debug", "ops"] = "telegram",
    manual: bool = False,
    occurred_at: datetime | None = None,
    metadata: Mapping[str, object] | None = None,
) -> InputEvent:
    payload: dict[str, object] = {
        "trigger": trigger,
        "delivery_channel": delivery_channel,
        "manual": manual,
        "window_status": None,
    }
    if metadata:
        payload.update(metadata)
    return InputEvent(
        id=f"heartbeat:{trigger}:{uuid4().hex}",
        user_id=user_id,
        source=source,
        type="weekly_review_tick" if trigger == "weekly_review" else "heartbeat_tick",
        text=None,
        payload=payload,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )


def heartbeat_draft_to_outcome(draft: CoachDraft | None, *, trigger: HeartbeatTrigger) -> DecisionOutcome:
    if draft is None:
        return DecisionOutcome(
            kind="no_send",
            commands=(),
            applied_commands=(),
            candidates=(),
            selected_candidate_id=None,
            explanation=DecisionExplanation(
                decision_label="Heartbeat no send",
                reason_summary="No proactive message was produced.",
                evidence=(f"trigger:{trigger}",),
                tradeoff=None,
                impact={},
                protected=(),
                next_step=None,
            ),
            reply_contract=ReplyContract(
                mode="heartbeat_no_send",
                audience="telegram",
                allowed_claims=(),
                forbidden_claims=("visible_reply",),
            ),
        )

    pending = draft.pending_confirmation
    if pending is not None:
        summary = str(pending.summary or draft.text or "").strip()
        return DecisionOutcome(
            kind="plan_pending",
            commands=(),
            applied_commands=(),
            candidates=(),
            selected_candidate_id=None,
            explanation=DecisionExplanation(
                decision_label="Heartbeat pending confirmation",
                reason_summary=summary,
                evidence=(f"trigger:{trigger}", "pending_confirmation"),
                tradeoff=None,
                impact={"mutation_type": pending.mutation_type, "impact_level": pending.impact_level},
                protected=("explicit_confirmation",),
                next_step="await_user_confirmation",
            ),
            reply_contract=ReplyContract(
                mode="heartbeat_plan_pending",
                audience="telegram",
                allowed_claims=("pending_created",),
                forbidden_claims=("plan_committed", "execution_updated_without_event"),
            ),
        )

    text = str(draft.text or "").strip()
    return DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Heartbeat ready",
            reason_summary=text,
            evidence=(f"trigger:{trigger}",),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="heartbeat_answer",
            audience="telegram",
            allowed_claims=("read_only_context", "reminder", "coach_feedback"),
            forbidden_claims=("plan_committed_without_event", "execution_updated_without_event"),
        ),
    )


def run_heartbeat_trigger(
    *,
    trigger: HeartbeatTrigger,
    legacy_factory: Callable[[], CoachDraft | None],
    user_id: int = 0,
    source: Literal["telegram", "scheduler", "ops"] = "scheduler",
    delivery_channel: Literal["telegram", "debug", "ops"] = "telegram",
    manual: bool = False,
    occurred_at: datetime | None = None,
    metadata: Mapping[str, object] | None = None,
    verifier: OutputVerifier | None = None,
    enforce_verifier: bool = False,
) -> HeartbeatRuntimeResult:
    event = build_heartbeat_input_event(
        user_id=user_id,
        trigger=trigger,
        source=source,
        delivery_channel=delivery_channel,
        manual=manual,
        occurred_at=occurred_at,
        metadata=metadata,
    )
    draft = legacy_factory()
    outcome = heartbeat_draft_to_outcome(draft, trigger=trigger)
    reply_text = str(draft.text).strip() if draft is not None else None
    verifier_reason = _verify_reply(reply_text, outcome, verifier=verifier)
    if enforce_verifier and verifier_reason:
        return HeartbeatRuntimeResult(
            event=event,
            outcome=heartbeat_draft_to_outcome(None, trigger=trigger),
            draft=None,
            reply_text=None,
            verifier_reason=verifier_reason,
        )
    return HeartbeatRuntimeResult(
        event=event,
        outcome=outcome,
        draft=draft,
        reply_text=reply_text,
        verifier_reason=verifier_reason,
    )


def run_heartbeat_endpoint(
    kind: str,
    legacy_factory: Callable[[], CoachDraft | None],
    *,
    user_id: int,
    delivery_channel: Literal["debug", "ops"],
) -> HeartbeatRuntimeResult | None:
    if not heartbeat_runtime_cutover_enabled():
        return None
    trigger = heartbeat_trigger_from_endpoint_kind(kind)
    if trigger is None:
        return None
    return run_heartbeat_trigger(
        trigger=trigger,
        legacy_factory=legacy_factory,
        user_id=user_id,
        source="ops",
        delivery_channel=delivery_channel,
        manual=True,
        enforce_verifier=heartbeat_runtime_verifier_enforced(),
    )


def heartbeat_trigger_from_endpoint_kind(kind: str) -> HeartbeatTrigger | None:
    return {
        "morning": "morning_briefing",
        "pre_session": "pre_session_reminder",
        "signal_check": "signal_check",
        "weekly_review": "weekly_review",
    }.get(kind)


def heartbeat_runtime_payload(result: HeartbeatRuntimeResult) -> dict[str, object | None]:
    return {
        "event_id": result.event.id,
        "event_type": result.event.type,
        "source": result.event.source,
        "trigger": result.event.payload.get("trigger"),
        "outcome": result.outcome.kind,
        "verifier_reason": result.verifier_reason,
    }


def _verify_reply(
    reply_text: str | None,
    outcome: DecisionOutcome,
    *,
    verifier: OutputVerifier | None,
) -> str | None:
    if not reply_text:
        return None
    checker = verifier or DecisionOutputVerifier()
    result = checker.verify(reply_text, outcome, None)
    if result.allowed:
        return None
    return result.reason or "blocked"
