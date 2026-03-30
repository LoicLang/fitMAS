from datetime import date

from fitmas.recent_reality import build_recent_reality_window


def test_recent_reality_counts_confirmed_sessions_and_load_gap() -> None:
    window = build_recent_reality_window(
        today=date(2026, 3, 30),
        scheduled_sessions=[
            {
                "id": 1,
                "sport_type": "running",
                "scheduled_date": "2026-03-25T07:00:00+01:00",
                "duration_min": 60,
                "intensity": "moderate",
                "load_score": 3,
                "priority": "High",
                "completion_status": "done",
            },
            {
                "id": 2,
                "sport_type": "swimming",
                "scheduled_date": "2026-03-27T07:00:00+01:00",
                "duration_min": 40,
                "intensity": "easy",
                "load_score": 1,
                "priority": "Support",
                "completion_status": "planned",
            },
            {
                "id": 3,
                "sport_type": "running",
                "scheduled_date": "2026-03-29T07:00:00+01:00",
                "duration_min": 50,
                "intensity": "easy",
                "load_score": 1,
                "priority": "Support",
                "completion_status": "planned",
            },
        ],
        activities=[
            {
                "id": 11,
                "sport_type": "running",
                "scheduled_session_id": 1,
                "started_at": "2026-03-25T07:02:00+01:00",
                "tss": 48.0,
            }
        ],
    )

    assert window.planned_sessions_7d == 3
    assert window.confirmed_sessions_7d == 1
    assert window.key_sessions_salvaged_7d == 1
    assert window.compliance_confirmed == 0.33
    assert window.load_ratio < 0.5
    assert window.missed_streak_days == 2
