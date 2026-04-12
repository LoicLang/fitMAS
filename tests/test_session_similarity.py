from __future__ import annotations

from datetime import date

from fitmas.session_similarity import find_same_sport_proximity_conflict


def test_finds_same_sport_type_proximity_conflict() -> None:
    conflict = find_same_sport_proximity_conflict(
        target_session_id=10,
        target_date=date(2026, 4, 15),
        scheduled_sessions=[
            {"id": 10, "scheduled_date": "2026-04-13", "sport_type": "running", "session_type": "tempo"},
            {"id": 11, "scheduled_date": "2026-04-16", "sport_type": "running", "session_type": "tempo"},
        ],
    )

    assert conflict is not None
    assert conflict.session_id == 11
    assert conflict.sport_type == "running"
    assert conflict.session_type == "tempo"


def test_ignores_different_session_type() -> None:
    conflict = find_same_sport_proximity_conflict(
        target_session_id=10,
        target_date=date(2026, 4, 15),
        scheduled_sessions=[
            {"id": 10, "scheduled_date": "2026-04-13", "sport_type": "running", "session_type": "tempo"},
            {"id": 11, "scheduled_date": "2026-04-16", "sport_type": "running", "session_type": "easy"},
        ],
    )

    assert conflict is None
