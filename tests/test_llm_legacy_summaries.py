from __future__ import annotations

from types import SimpleNamespace

import fitmas.llm.legacy_summaries as legacy_summaries


def test_make_plan_summary_keeps_core_training_fields() -> None:
    day = SimpleNamespace(
        label="Mardi",
        day="Tuesday",
        sport_type="running",
        session_title="Footing 45min",
        session_goal="Construire l'endurance",
        priority="Seance cle",
        flexibility="mobile",
    )

    summary = legacy_summaries.make_plan_summary([day])

    assert "[running] Footing 45min" in summary
    assert "Construire l'endurance" in summary
    assert "priorite: Seance cle" in summary
    assert "flexibilite: mobile" in summary


def test_timeline_summary_marks_closed_sessions_not_swappable() -> None:
    session = SimpleNamespace(
        id=42,
        scheduled_date="2026-05-18",
        day="Monday",
        sport_type="running",
        session_type="easy",
        session_title="Footing",
        session_goal="Aerobie",
        completion_status="done",
    )

    summary = legacy_summaries.make_timeline_summary([session])

    assert "slot=closed" in summary
    assert "movable_target=false" in summary
    assert "swappable=false" in summary
    assert "can_swap_with_training=false" in summary


def test_timeline_summary_marks_rest_as_free_flexible() -> None:
    session = SimpleNamespace(
        id=43,
        scheduled_date="2026-05-19",
        day="Tuesday",
        sport_type="rest",
        session_type="rest",
        session_title="Repos",
        session_goal="Recuperer",
        completion_status="planned",
    )

    summary = legacy_summaries.make_timeline_summary([session])

    assert "slot=free_flexible" in summary
    assert "movable_target=true" in summary
    assert "swappable=true" in summary


def test_timeline_summary_marks_active_training_as_swappable() -> None:
    session = SimpleNamespace(
        id=44,
        scheduled_date="2026-05-20",
        day="Wednesday",
        sport_type="cycling",
        session_type="endurance",
        session_title="Velo endurance",
        session_goal="Volume facile",
        completion_status="planned",
    )

    summary = legacy_summaries.make_timeline_summary([session])

    assert "slot=training" in summary
    assert "movable_target=false" in summary
    assert "swappable=true" in summary
    assert "can_swap_with_training=true" in summary
