from __future__ import annotations

from fitmas.legacy.decision.coach_decision_runtime import (
    legacy_provider_skip_reason,
    trace_legacy_provider_skipped,
)


def test_legacy_provider_gate_denies_unknown_lane_permanently() -> None:
    assert legacy_provider_skip_reason({}) == "coach_decision_provider_removed"


def test_legacy_provider_gate_keeps_canonical_owner_reason_for_planning() -> None:
    turn_context: dict[str, object] = {
        "canonical_planning_provider": {
            "result": "fallback_legacy",
            "fallback_reason": "unsupported_requested_change",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_skip_reason(turn_context) == "canonical_planning_provider:unsupported_requested_change"


def test_legacy_provider_gate_keeps_canonical_owner_reason_for_pending() -> None:
    turn_context: dict[str, object] = {
        "canonical_pending_provider": {
            "result": "no_pending_resolution",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_skip_reason(turn_context) == "canonical_pending_provider:no_pending_resolution"


def test_legacy_provider_gate_keeps_canonical_owner_reason_for_readonly_reply() -> None:
    turn_context: dict[str, object] = {
        "canonical_readonly_reply": {
            "composed": False,
            "reason": "reply_contract",
            "deny_legacy_provider": True,
        }
    }

    assert legacy_provider_skip_reason(turn_context) == "canonical_readonly_reply:reply_contract"


def test_trace_legacy_provider_skipped_records_removed_provider_trace() -> None:
    turn_context: dict[str, object] = {}

    trace_legacy_provider_skipped(turn_context, reason="coach_decision_provider_removed")

    assert turn_context["legacy_decide"] == {
        "legacy_skipped": True,
        "source": "legacy_provider_gate",
        "reason": "coach_decision_provider_removed",
    }
