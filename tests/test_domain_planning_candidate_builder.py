from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.coach_voice import message_has_user_facing_internal_jargon
from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.domain.planning.models import PlanChangeReference, ResolvedPlanChange


def _session(
    session_id: int,
    scheduled_date: str = "2026-05-14",
    duration_min: int = 45,
    *,
    sport_type: str = "running",
    completion_status: str | None = None,
):
    return SimpleNamespace(
        id=session_id,
        scheduled_date=scheduled_date,
        session_title="Tempo",
        sport_type=sport_type,
        session_type="tempo",
        duration_min=duration_min,
        completion_status=completion_status,
    )


def _context(*sessions):
    return SimpleNamespace(plan=SimpleNamespace(scheduled_sessions=tuple(sessions)))


def _resolved(
    kind: str,
    *,
    source_session_id: int | None,
    target_date: date | None,
    desired_sport: str | None = None,
    desired_intensity: str | None = None,
):
    requested = RequestedPlanChange(
        kind=kind,
        source_ref=f"session_id:{source_session_id}" if source_session_id else None,
        target_ref=f"date:{target_date.isoformat()}" if target_date else None,
        desired_sport=desired_sport,
        desired_duration_min=None,
        desired_intensity=desired_intensity,
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


def _window_resolved(
    *,
    starts_on: date = date(2026, 5, 20),
    ends_on: date = date(2026, 5, 22),
) -> ResolvedPlanChange:
    requested = RequestedPlanChange(
        kind="constraint_window",
        source_ref=f"availability_window:unavailable:general:{starts_on.isoformat()}:{ends_on.isoformat()}",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="travel",
        risk_signals=("availability",),
    )
    return ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(
            kind="availability_window",
            raw=requested.source_ref,
            session_id=None,
            date=None,
            scope="general",
            availability="unavailable",
            starts_on=starts_on,
            ends_on=ends_on,
        ),
        target=PlanChangeReference(kind="unknown", raw=None, session_id=None, date=None),
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


def test_builder_builds_replace_candidate_from_requested_sport_and_intensity_alias() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42, duration_min=40))).build(
        _resolved(
            "replace",
            source_session_id=42,
            target_date=None,
            desired_sport="velo",
            desired_intensity="facile",
        )
    )

    assert len(candidate_set.candidates) == 1
    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    operation = patch.operations[0]
    assert operation.operation_type == "replace_session"
    assert operation.target_session_id == 42
    assert operation.new_sport_type == "cycling"
    assert operation.new_session_type == "easy"
    assert operation.new_duration_min == 30
    assert operation.new_intensity == "easy"


def test_builder_builds_create_candidate_from_typed_target_and_sport() -> None:
    candidate_set = PlanCandidateBuilder(_context()).build(
        _resolved(
            "create",
            source_session_id=None,
            target_date=date(2026, 5, 20),
            desired_sport="running",
            desired_intensity="easy",
        )
    )

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:create_session:2026-05-20:running_30"
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    operation = patch.operations[0]
    assert operation.operation_type == "create_session"
    assert operation.target_date == "2026-05-20"
    assert operation.new_sport_type == "running"
    assert operation.new_intensity == "easy"


def test_builder_normalizes_create_high_intensity_to_hard() -> None:
    candidate_set = PlanCandidateBuilder(_context()).build(
        _resolved(
            "create",
            source_session_id=None,
            target_date=date(2026, 5, 26),
            desired_sport="course",
            desired_intensity="high",
        )
    )

    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    operation = patch.operations[0]
    assert operation.new_sport_type == "running"
    assert operation.new_session_type == "quality"
    assert operation.new_intensity == "hard"


def test_builder_does_not_infer_sport_for_create_candidate() -> None:
    candidate_set = PlanCandidateBuilder(_context()).build(
        _resolved(
            "create",
            source_session_id=None,
            target_date=date(2026, 5, 20),
            desired_sport=None,
            desired_intensity="hard",
        )
    )

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}


def test_builder_builds_multi_move_candidate_for_unavailable_window() -> None:
    candidate_set = PlanCandidateBuilder(
        _context(
            _session(1, "2026-05-20", sport_type="running"),
            _session(2, "2026-05-22", sport_type="strength"),
            _session(3, "2026-05-24", sport_type="cycling"),
        )
    ).build(_window_resolved())

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:constraint_window:2026-05-20:2026-05-22:move_after"
    assert "availability" in candidate.risk_notes
    assert "multi_day" in candidate.risk_notes
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    assert [operation.operation_type for operation in patch.operations] == ["move_session", "move_session"]
    assert [operation.target_session_id for operation in patch.operations] == [1, 2]
    assert [operation.target_date for operation in patch.operations] == ["2026-05-23", "2026-05-25"]


def test_builder_returns_empty_when_window_has_no_open_targets() -> None:
    candidate_set = PlanCandidateBuilder(
        _context(
            _session(1, "2026-05-20", sport_type="running"),
            _session(2, "2026-05-23", sport_type="cycling"),
            _session(3, "2026-05-24", sport_type="strength"),
            _session(4, "2026-05-25", sport_type="running"),
            _session(5, "2026-05-26", sport_type="cycling"),
            _session(6, "2026-05-27", sport_type="strength"),
            _session(7, "2026-05-28", sport_type="running"),
            _session(8, "2026-05-29", sport_type="cycling"),
            _session(9, "2026-05-30", sport_type="strength"),
            _session(10, "2026-05-31", sport_type="running"),
            _session(11, "2026-06-01", sport_type="cycling"),
        )
    ).build(_window_resolved())

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}


def test_builder_builds_replace_candidates_from_sport_window() -> None:
    requested = RequestedPlanChange(
        kind="replace",
        source_ref="sport_window:swimming:2026-05-18:2026-06-01",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="swim unavailable",
        risk_signals=("availability",),
    )
    resolved = ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(
            kind="sport_window",
            raw=requested.source_ref,
            session_id=None,
            date=None,
            sport_type="swimming",
            starts_on=date(2026, 5, 18),
            ends_on=date(2026, 6, 1),
        ),
        target=PlanChangeReference(kind="unknown", raw=None, session_id=None, date=None),
        warnings=(),
    )

    candidate_set = PlanCandidateBuilder(
        _context(
            _session(41, "2026-05-20", sport_type="running"),
            _session(42, "2026-05-24", duration_min=45, sport_type="swimming"),
            _session(43, "2026-06-03", sport_type="swimming"),
            _session(44, "2026-05-25", sport_type="swimming", completion_status="done"),
        )
    ).build(resolved)

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:replace_unavailable_sport:42:swimming"
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    operation = patch.operations[0]
    assert operation.operation_type == "replace_session"
    assert operation.target_session_id == 42
    assert operation.new_sport_type == "strength"
    assert operation.new_session_type == "support"
    assert operation.new_duration_min == 30
    assert operation.new_intensity == "easy"


def test_builder_returns_empty_set_for_unresolved_source() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42))).build(
        _resolved("move", source_session_id=None, target_date=date(2026, 5, 15))
    )

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}
