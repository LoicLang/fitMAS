from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone

import pytest

from fitmas.legacy.decision import (
    AthleteContext,
    CoachContext,
    CoachUnderstanding,
    Command,
    CommandResult,
    DecisionExplanation,
    DecisionOutcome,
    ExecutionReality,
    InputEvent,
    LoadContext,
    LocalTimeContext,
    MemoryContext,
    PendingContext,
    PlanTimeline,
    ReadinessContext,
    ReplyContract,
    RequestedPlanChange,
    WeeklyRealityDigest,
)


def _field_names(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def test_decision_runtime_types_are_plain_dataclasses() -> None:
    for cls in (
        InputEvent,
        CoachContext,
        CoachUnderstanding,
        RequestedPlanChange,
        DecisionExplanation,
        ReplyContract,
        Command,
        CommandResult,
        DecisionOutcome,
    ):
        assert is_dataclass(cls), cls


def test_input_event_represents_user_message_without_runtime_side_effects() -> None:
    event = InputEvent(
        id="evt_1",
        user_id=42,
        source="telegram",
        type="user_message",
        text="deplace la seance a vendredi",
        payload={"client_message_key": "telegram:1"},
        occurred_at=datetime(2026, 5, 14, 8, 30, tzinfo=timezone.utc),
    )

    assert event.id == "evt_1"
    assert event.user_id == 42
    assert event.source == "telegram"
    assert event.type == "user_message"
    assert event.text == "deplace la seance a vendredi"
    assert event.payload == {"client_message_key": "telegram:1"}


def test_coach_context_groups_truth_by_domain_without_reply_or_patch_fields() -> None:
    local_time = LocalTimeContext(
        timezone_name="Europe/Paris",
        now_iso="2026-05-14T08:30+02:00",
        today_iso="2026-05-14",
        time_context={"day_label_fr": "jeudi"},
    )
    plan = PlanTimeline(
        scheduled_sessions=("session-1",),
        session_policies=("policy-1",),
        planning_contract="contract",
        week_mission="mission",
        latest_adaptation=None,
        recent_adaptations=(),
    )
    execution = ExecutionReality(
        activities=("activity-1",),
        recent_reality="recent",
        today_execution=None,
    )
    memory = MemoryContext(active_memory=("profile",), active_facts=())
    athlete = AthleteContext(profile_snapshot="profile", calibration_status="calibration")
    readiness = ReadinessContext(snapshot=None, state=None)
    load = LoadContext(summary=None, forecast=None)
    weekly_digest = WeeklyRealityDigest(
        week_summary={"total_sessions": 1},
        planning_context={"mode": "maintain_load"},
        next_week={"focus": "stability"},
        coach_reading="Semaine stable.",
    )
    pending = PendingContext(active_pending=None, summary=None)

    context = CoachContext(
        user="user",
        local_time=local_time,
        plan=plan,
        execution=execution,
        memory=memory,
        athlete=athlete,
        readiness=readiness,
        load=load,
        weekly_digest=weekly_digest,
        pending=pending,
    )

    forbidden = {"fitmas_message", "reply_text", "plan_patch", "mutation_decision", "commands"}

    assert context.plan.scheduled_sessions == ("session-1",)
    assert context.weekly_digest.week_summary["total_sessions"] == 1
    assert _field_names(CoachContext).isdisjoint(forbidden)


def test_coach_understanding_cannot_carry_visible_reply_or_plan_patch() -> None:
    requested_change = RequestedPlanChange(
        kind="move",
        source_ref="seance de ce soir",
        target_ref="vendredi",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )
    understanding = CoachUnderstanding(
        intent="plan_change",
        confidence=0.88,
        user_summary="fatigue et demande de deplacement",
        extracted_signals=(),
        requested_change=requested_change,
        pending_resolution=None,
        clarification_need=None,
    )

    forbidden = {
        "fitmas_message",
        "reply_text",
        "final_reply",
        "plan_patch",
        "mutation_decision",
    }

    assert understanding.requested_change == requested_change
    assert _field_names(CoachUnderstanding).isdisjoint(forbidden)
    assert _field_names(RequestedPlanChange).isdisjoint({"plan_patch", "patch", "operations"})


def test_user_signal_pending_resolution_and_clarification_need_are_typed() -> None:
    from fitmas.legacy.decision import ClarificationNeed, PendingResolution, UserSignal

    signal = UserSignal(
        type="health",
        label="poor_sleep",
        status="new",
        severity="moderate",
        confidence=0.82,
        evidence="dormi 4h",
        payload={"affects": ("readiness",)},
    )
    pending = PendingResolution(
        type="modify_pending",
        reason="user changed target day",
        selected_candidate_id=None,
        requested_changes="vendredi plutot que mercredi",
        question=None,
    )
    clarification = ClarificationNeed(
        reason="target session ambiguous",
        missing_fields=("source_ref",),
        question_intent="identify_target_session",
    )

    assert signal.type == "health"
    assert signal.payload["affects"] == ("readiness",)
    assert pending.type == "modify_pending"
    assert clarification.missing_fields == ("source_ref",)


def test_coach_understanding_accepts_typed_signals_and_rejects_bad_confidence() -> None:
    from fitmas.legacy.decision import ClarificationNeed, CoachUnderstanding, UserSignal

    signal = UserSignal(
        type="availability",
        label="pool_closed",
        status="new",
        severity="unknown",
        confidence=0.77,
        evidence="piscine fermee",
        payload={"sport_type": "swimming"},
    )

    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.77,
        user_summary="piscine indisponible",
        extracted_signals=(signal,),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    assert understanding.extracted_signals == (signal,)
    assert understanding.clarification_need is None

    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        CoachUnderstanding(
            intent="general_answer",
            confidence=1.3,
            user_summary="bad confidence",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=None,
            clarification_need=ClarificationNeed(
                reason="not used",
                missing_fields=(),
                question_intent="none",
            ),
        )


@pytest.mark.parametrize(
    "kind",
    ("answer", "plan_committed", "plan_pending", "plan_blocked"),
)
def test_decision_outcome_represents_core_outcome_kinds(kind: str) -> None:
    explanation = DecisionExplanation(
        decision_label="Decision",
        reason_summary="Reason",
        evidence=("scheduled truth",),
        tradeoff=None,
        impact={},
        protected=(),
        next_step=None,
    )
    reply_contract = ReplyContract(
        mode="compose",
        audience="user",
        allowed_claims=("events_only",),
        forbidden_claims=("uncommitted_action",),
    )

    outcome = DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=explanation,
        reply_contract=reply_contract,
    )

    assert outcome.kind == kind
    assert outcome.explanation.reason_summary == "Reason"
    assert outcome.reply_contract.allowed_claims == ("events_only",)


def test_command_result_requires_event_reference_for_applied_write() -> None:
    command = Command(
        id="cmd_1",
        domain="planning",
        name="move_session",
        payload={"session_id": 12, "target_date": "2026-05-15"},
    )
    result = CommandResult(
        command_id=command.id,
        domain=command.domain,
        name=command.name,
        status="applied",
        event_id="plan_event_1",
        payload={"session_id": 12},
    )

    assert command.domain == "planning"
    assert result.event_id == "plan_event_1"

    with pytest.raises(ValueError, match="applied command results must reference an event"):
        CommandResult(
            command_id=command.id,
            domain=command.domain,
            name=command.name,
            status="applied",
            event_id=None,
            payload={},
        )
