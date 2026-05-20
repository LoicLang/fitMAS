from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.legacy.coach_decision_provider import CoachDecisionResult
from fitmas.legacy.conversation_decide_bridge import (
    build_legacy_coach_decision_request,
    legacy_provider_allowed_for_turn,
    legacy_provider_skip_reason,
    run_legacy_coach_decision,
    trace_legacy_provider_skipped,
)


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return self.result


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        coach_name="FitMAS",
        coach_style="direct",
        coach_relationship="coach",
        coach_do="court",
        coach_dont="long",
        coach_soul="sobre",
        timezone="Europe/Paris",
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        timeline=("timeline-item",),
        conversation_history=[{"role": "user", "text": "avant"}, {"role": "user", "text": "courant"}],
        active_facts=[{"key": "availability:x"}],
        active_memory_rows=[],
        today_session=SimpleNamespace(id=12),
        scheduled_sessions=(),
        activities=(),
    )


def _coach_bundle() -> SimpleNamespace:
    return SimpleNamespace(
        planning_contract=SimpleNamespace(as_dict=lambda: {"planning": "contract"}),
        availability_state=SimpleNamespace(as_dict=lambda: {"availability": "state"}),
        week_mission=SimpleNamespace(as_dict=lambda: {"week": "mission"}),
        recent_reality=SimpleNamespace(as_dict=lambda: {"recent": "reality"}),
        latest_adaptation=None,
        week_summary="week",
        planning_context="planning",
        next_week="next",
        coach_reading="reading",
    )


def test_build_request_carries_machine_context_only() -> None:
    request = build_legacy_coach_decision_request(
        user_text="deplace vendredi",
        user=_user(),
        state=_state(),
        turn_plan=SimpleNamespace(
            primary_intent="plan_mutation",
            secondary_intents=("availability_constraint",),
        ),
        coach_bundle=_coach_bundle(),
        conversation_context=SimpleNamespace(time_context={"today": "2026-05-15"}),
        timeline_summary="timeline summary",
        execution_summary="execution summary",
        temporal_summary="temporal summary",
        activity_claim_summary="claim summary",
        signal_summary="signal summary",
        selected_facts=[{"key": "selected"}],
        profile_summary="profile",
        coach_reading_digest_text="digest",
        unresolved_execution_followup_text=None,
        unresolved_execution_followup_session_id=None,
        unresolved_execution_followup_target_date=None,
        tool_context=SimpleNamespace(pipeline="conversation"),
    )

    assert request.user_text == "deplace vendredi"
    assert request.coach_context["turn_primary_intent"] == "plan_mutation"
    assert request.coach_context["turn_secondary_intents"] == ["availability_constraint"]
    assert request.coach_context["planning_contract"] == {"planning": "contract"}
    assert request.conversation_history == [{"role": "user", "text": "avant"}]
    assert request.tool_context.pipeline == "conversation"


def test_run_legacy_coach_decision_records_trace() -> None:
    returned = SimpleNamespace(response_type="no_change", fitmas_message="ok")
    provider = FakeProvider(
        CoachDecisionResult(
            artifact=legacy_decision_artifact_from_raw(returned),
            raw_decision=returned,
        )
    )
    turn_context: dict[str, object] = {}

    request = build_legacy_coach_decision_request(
        user_text="ok",
        user=_user(),
        state=_state(),
        turn_plan=SimpleNamespace(primary_intent="close_turn", secondary_intents=()),
        coach_bundle=_coach_bundle(),
        conversation_context=SimpleNamespace(time_context={}),
        timeline_summary="",
        execution_summary="",
        temporal_summary="",
        activity_claim_summary="",
        signal_summary="",
        selected_facts=[],
        profile_summary="",
        coach_reading_digest_text=None,
        unresolved_execution_followup_text=None,
        unresolved_execution_followup_session_id=None,
        unresolved_execution_followup_target_date=None,
        tool_context=None,
    )

    result = run_legacy_coach_decision(provider=provider, request=request, turn_context=turn_context)

    assert result.kind == "coach_decision"
    assert result.reply_hint == "ok"
    assert turn_context["legacy_decide"]["source"] == "legacy_coach_decision"
    assert turn_context["legacy_decide"]["ok"] is True
    assert turn_context["legacy_decide"]["artifact_kind"] == "coach_decision"
    assert turn_context["legacy_decide"]["response_type"] == "no_change"
    assert turn_context["legacy_decide"]["decision_present"] is True
    assert "raw_decision" not in turn_context["legacy_decide"]
    assert turn_context["fallback_census"][0]["owner"] == "legacy_provider"
    assert turn_context["fallback_census"][0]["source"] == "legacy_decide"
    assert turn_context["fallback_census"][0]["legacy_path"] == "CoachDecision"


def test_run_legacy_coach_decision_records_planning_fallback_owner() -> None:
    returned = SimpleNamespace(response_type="no_change", fitmas_message="ok")
    provider = FakeProvider(
        CoachDecisionResult(
            artifact=legacy_decision_artifact_from_raw(returned),
            raw_decision=returned,
        )
    )
    turn_context: dict[str, object] = {
        "canonical_planning_provider": {
            "result": "fallback_legacy",
            "fallback_reason": "unsupported_requested_change",
        }
    }
    request = build_legacy_coach_decision_request(
        user_text="ok",
        user=_user(),
        state=_state(),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=()),
        coach_bundle=_coach_bundle(),
        conversation_context=SimpleNamespace(time_context={}),
        timeline_summary="",
        execution_summary="",
        temporal_summary="",
        activity_claim_summary="",
        signal_summary="",
        selected_facts=[],
        profile_summary="",
        coach_reading_digest_text=None,
        unresolved_execution_followup_text=None,
        unresolved_execution_followup_session_id=None,
        unresolved_execution_followup_target_date=None,
        tool_context=None,
    )

    run_legacy_coach_decision(provider=provider, request=request, turn_context=turn_context)

    assert turn_context["fallback_census"][0]["owner"] == "planning"
    assert turn_context["fallback_census"][0]["source"] == "canonical_planning_provider"
    assert turn_context["fallback_census"][0]["reason"] == "unsupported_requested_change"


def test_legacy_provider_gate_allows_unknown_unprepared_lane() -> None:
    turn_context: dict[str, object] = {}

    assert legacy_provider_allowed_for_turn(turn_context) is True
    assert legacy_provider_skip_reason(turn_context) is None


def test_legacy_provider_gate_denies_canonical_planning_lane() -> None:
    turn_context: dict[str, object] = {
        "canonical_planning_provider": {
            "result": "fallback_legacy",
            "fallback_reason": "unsupported_requested_change",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_allowed_for_turn(turn_context) is False
    assert legacy_provider_skip_reason(turn_context) == "canonical_planning_provider:unsupported_requested_change"


def test_legacy_provider_gate_denies_pending_lane() -> None:
    turn_context: dict[str, object] = {
        "canonical_pending_provider": {
            "result": "no_pending_resolution",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_allowed_for_turn(turn_context) is False
    assert legacy_provider_skip_reason(turn_context) == "canonical_pending_provider:no_pending_resolution"


def test_legacy_provider_gate_denies_readonly_reply_lane() -> None:
    turn_context: dict[str, object] = {
        "canonical_readonly_reply": {
            "composed": False,
            "reason": "reply_contract",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_allowed_for_turn(turn_context) is False
    assert legacy_provider_skip_reason(turn_context) == "canonical_readonly_reply:reply_contract"


def test_trace_legacy_provider_skipped_records_non_active_legacy_trace() -> None:
    turn_context: dict[str, object] = {}

    trace_legacy_provider_skipped(turn_context, reason="canonical_planning_provider:unsupported_requested_change")

    assert turn_context["legacy_decide"] == {
        "legacy_skipped": True,
        "source": "legacy_provider_gate",
        "reason": "canonical_planning_provider:unsupported_requested_change",
    }


def test_legacy_provider_gate_allows_classified_fallback_without_hard_deny() -> None:
    turn_context: dict[str, object] = {
        "canonical_planning_provider": {
            "result": "fallback_legacy",
            "fallback_reason": "compat_lane_not_migrated",
        }
    }

    assert legacy_provider_allowed_for_turn(turn_context) is True
    assert legacy_provider_skip_reason(turn_context) is None
