from __future__ import annotations

from fitmas.runtime_v0.proposals import (
    ActionProposal,
    WeekProposalDraft,
    proposal_from_dict,
    proposal_to_dict,
)


def _draft() -> WeekProposalDraft:
    return WeekProposalDraft(
        week_start="2026-06-08",
        source="llm",
        week_load=315.0,
        band=(300.0, 330.0),
        key_type="threshold",
        sessions=(
            {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": "3x8"},
            {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate", "detail": ""},
        ),
    )


def test_week_proposal_roundtrips():
    proposal = ActionProposal(
        type="week_proposal",
        confidence=0.8,
        user_intent_summary="week proposal",
        evidence=("semaine proposée",),
        answer_facts=("semaine proposée",),
        week_proposal=_draft(),
    )
    restored = proposal_from_dict(proposal_to_dict(proposal))
    assert restored.type == "week_proposal"
    assert restored.week_proposal == _draft()
    assert restored.week_proposal.band == (300.0, 330.0)
    assert restored.week_proposal.sessions[0]["type"] == "threshold"
