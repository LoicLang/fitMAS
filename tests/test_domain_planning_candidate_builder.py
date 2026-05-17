from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.coach_voice import message_has_user_facing_internal_jargon
from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.domain.planning.models import PlanChangeReference, ResolvedPlanChange


def _session(session_id: int, scheduled_date: str = "2026-05-14", duration_min: int = 45):
    return SimpleNamespace(
        id=session_id,
        scheduled_date=scheduled_date,
        session_title="Tempo",
        sport_type="running",
        session_type="tempo",
        duration_min=duration_min,
        completion_status=None,
    )


def _context(*sessions):
    return SimpleNamespace(plan=SimpleNamespace(scheduled_sessions=tuple(sessions)))


def _resolved(kind: str, *, source_session_id: int | None, target_date: date | None):
    requested = RequestedPlanChange(
        kind=kind,
        source_ref=f"session_id:{source_session_id}" if source_session_id else None,
        target_ref=f"date:{target_date.isoformat()}" if target_date else None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )
    return ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(
            kind="session" if source_session_id else "unknown",
            raw=requested.source_ref,
            session_id=source_session_id,
            date=None,
        ),
        target=PlanChangeReference(
            kind="date" if target_date else "unknown",
            raw=requested.target_ref,
            session_id=None,
            date=target_date,
        ),
        warnings=(),
    )


def test_builder_builds_move_candidate_from_resolved_refs() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42))).build(
        _resolved("move", source_session_id=42, target_date=date(2026, 5, 15))
    )

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:move_session:42:2026-05-15"
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    assert patch.operations[0].operation_type == "move_session"
    assert patch.operations[0].target_session_id == 42
    assert patch.operations[0].target_date == "2026-05-15"
    assert not message_has_user_facing_internal_jargon(patch.coach_message)
    assert "Candidate backend" not in patch.coach_message


def test_builder_builds_lighten_candidate() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42, duration_min=50))).build(
        _resolved("lighten", source_session_id=42, target_date=None)
    )

    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    assert patch.operations[0].operation_type == "lighten_day"
    assert patch.operations[0].new_duration_min == 30
    assert patch.operations[0].new_intensity == "easy"


def test_builder_returns_empty_set_for_unresolved_source() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42))).build(
        _resolved("move", source_session_id=None, target_date=date(2026, 5, 15))
    )

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}
