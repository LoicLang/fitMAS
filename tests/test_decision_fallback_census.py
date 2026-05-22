from __future__ import annotations

import pytest

from fitmas.decision.fallback_census import (
    fallback_entries,
    record_fallback,
    record_legacy_provider_fallback,
    unclassified_legacy_fallback_reasons,
)


def test_record_fallback_requires_known_owner_source_and_reason() -> None:
    turn_context: dict[str, object] = {}

    entry = record_fallback(
        turn_context,
        owner="planning",
        source="canonical_planning_provider",
        reason="unsupported_requested_change",
        legacy_path="CoachDecision",
        next_step="migrate requested_change coverage",
    )

    assert entry["owner"] == "planning"
    assert entry["source"] == "canonical_planning_provider"
    assert entry["reason"] == "unsupported_requested_change"
    assert entry["legacy_path"] == "CoachDecision"
    assert entry["severity"] == "needs_migration"
    assert fallback_entries(turn_context) == (entry,)

    with pytest.raises(ValueError, match="unknown fallback owner"):
        record_fallback(turn_context, owner="misc", source="x", reason="y")
    with pytest.raises(ValueError, match="fallback source is required"):
        record_fallback(turn_context, owner="planning", source="", reason="y")
    with pytest.raises(ValueError, match="fallback reason is required"):
        record_fallback(turn_context, owner="planning", source="x", reason="")


def test_unclassified_legacy_fallback_detects_active_legacy_decide_without_census() -> None:
    turn_context = {"legacy_decide": {"legacy_skipped": False, "source": "legacy_coach_decision"}}

    assert unclassified_legacy_fallback_reasons(turn_context) == (
        "legacy fallback used without fallback census",
    )


def test_legacy_provider_fallback_classifies_from_planning_trace() -> None:
    turn_context = {
        "canonical_planning_provider": {
            "result": "fallback_legacy",
            "fallback_reason": "unsupported_requested_change",
        }
    }

    entry = record_legacy_provider_fallback(turn_context, response_type="no_change", ok=True)

    assert entry["owner"] == "planning"
    assert entry["source"] == "canonical_planning_provider"
    assert entry["reason"] == "unsupported_requested_change"
    assert entry["legacy_path"] == "CoachDecision"
    assert entry["metadata"]["response_type"] == "no_change"
    assert entry["metadata"]["ok"] is True
    assert unclassified_legacy_fallback_reasons(
        {
            "legacy_decide": {"legacy_skipped": False},
            "fallback_census": (entry,),
        }
    ) == ()
