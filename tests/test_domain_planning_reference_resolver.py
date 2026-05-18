from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.reference_resolver import ReferenceResolver


def _context(*sessions):
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-14"),
        plan=SimpleNamespace(scheduled_sessions=tuple(sessions)),
    )


def _session(session_id: int, scheduled_date: str):
    return SimpleNamespace(id=session_id, scheduled_date=scheduled_date, duration_min=45)


def test_resolver_resolves_session_id_and_date_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.source.kind == "session"
    assert resolved.source.session_id == 42
    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.warnings == ()


def test_resolver_resolves_day_ref_against_current_week() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="day:friday",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)


def test_resolver_accepts_iso_date_refs_from_typed_understanding() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.warnings == ()


def test_resolver_accepts_day_iso_refs_from_typed_understanding() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="day:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.warnings == ()


def test_resolver_promotes_swap_date_refs_to_sessions_when_unambiguous() -> None:
    requested = RequestedPlanChange(
        kind="swap",
        source_ref="date:2026-05-20",
        target_ref="date:2026-05-21",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="swap days",
        risk_signals=(),
    )

    resolved = ReferenceResolver(
        _context(_session(1, "2026-05-20"), _session(2, "2026-05-21"))
    ).resolve(requested)

    assert resolved.source.kind == "session"
    assert resolved.source.session_id == 1
    assert resolved.target.kind == "session"
    assert resolved.target.session_id == 2
    assert resolved.warnings == ()


def test_resolver_keeps_ambiguous_date_source_unresolved() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="date:2026-05-20",
        target_ref="date:2026-05-22",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="move day",
        risk_signals=(),
    )

    resolved = ReferenceResolver(
        _context(_session(1, "2026-05-20"), _session(2, "2026-05-20"))
    ).resolve(requested)

    assert resolved.source.kind == "date"
    assert "unresolved_source_ref" in resolved.warnings


def test_resolver_does_not_guess_unknown_free_text_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="la seance dure de ce soir",
        target_ref="vendredi",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.source.kind == "unknown"
    assert resolved.target.kind == "unknown"
    assert "unresolved_source_ref" in resolved.warnings
    assert "unresolved_target_ref" in resolved.warnings
