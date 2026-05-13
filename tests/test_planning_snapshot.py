from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from fitmas.planning_snapshot import build_planning_snapshot_from_records


def _session(
    *,
    session_id: int,
    day: date,
    sport_type: str,
    session_type: str,
    title: str = "",
    goal: str = "",
    description: str = "",
    duration_min: int | None = None,
    intensity: str = "easy",
    load_score: int = 0,
    completion_status: str = "planned",
):
    return SimpleNamespace(
        id=session_id,
        scheduled_date=datetime.combine(day, datetime.min.time()),
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        session_goal=goal,
        session_note="",
        session_description=description,
        duration_min=duration_min,
        intensity=intensity,
        load_score=load_score,
        priority="Normal",
        flexibility="stable",
        completion_status=completion_status,
    )


def _memory(**kwargs):
    return SimpleNamespace(**kwargs)


def test_snapshot_marks_clean_rest_as_full_rest() -> None:
    snapshot = build_planning_snapshot_from_records(
        user_id=1,
        timezone_name="Europe/Paris",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 15),
        sessions=[
            _session(
                session_id=10,
                day=date(2026, 5, 15),
                sport_type="rest",
                session_type="rest",
                title="Repos total",
                load_score=0,
            )
        ],
        memory_rows=[],
        now=datetime(2026, 5, 13, 12, 0),
    )

    day = snapshot.days[0]

    assert day.day_kind == "rest_total"
    assert day.is_full_rest is True
    assert day.load_score == 0
    assert day.items[0].load_kind == "zero"
    assert snapshot.diagnostics == ()


def test_snapshot_exposes_rest_with_session_detail_as_unscored_recovery() -> None:
    snapshot = build_planning_snapshot_from_records(
        user_id=1,
        timezone_name="Europe/Paris",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 15),
        sessions=[
            _session(
                session_id=11,
                day=date(2026, 5, 15),
                sport_type="rest",
                session_type="rest",
                title="Repos actif",
                goal="Mobilite + marche legere",
                description="20 min de mobilite, respiration, marche facile.",
                duration_min=20,
                load_score=0,
            )
        ],
        memory_rows=[],
        now=datetime(2026, 5, 13, 12, 0),
    )

    day = snapshot.days[0]
    item = day.items[0]

    assert day.day_kind == "active_recovery"
    assert day.is_full_rest is False
    assert item.load_kind == "unscored_recovery"
    assert item.unscored_reason == "rest_with_session_content"
    assert "REST_WITH_SESSION_CONTENT:session:11" in snapshot.diagnostics


def test_snapshot_includes_only_current_active_availability_constraints() -> None:
    snapshot = build_planning_snapshot_from_records(
        user_id=1,
        timezone_name="Europe/Paris",
        start_date=date(2026, 5, 13),
        end_date=date(2026, 5, 15),
        sessions=[],
        memory_rows=[
            _memory(
                category="availability",
                key="availability_2026-05-13_2026-05-14",
                value="unavailable: inondations",
                active=True,
                status="open",
                signal_kind="availability_unavailable",
                valid_from=datetime(2026, 5, 13),
                valid_until=datetime(2026, 5, 15),
                expires_at=datetime(2026, 5, 15),
            ),
            _memory(
                category="availability",
                key="availability_2026-05-10_2026-05-10",
                value="unavailable: ancien",
                active=False,
                status="resolved",
                signal_kind="availability_unavailable",
                valid_from=datetime(2026, 5, 10),
                valid_until=datetime(2026, 5, 11),
                expires_at=datetime(2026, 5, 11),
            ),
        ],
        now=datetime(2026, 5, 13, 12, 0),
    )

    assert len(snapshot.active_constraints) == 1
    assert snapshot.active_constraints[0].kind == "availability_unavailable"
    assert snapshot.active_constraints[0].starts_on == "2026-05-13"
    assert snapshot.active_constraints[0].ends_on == "2026-05-14"
