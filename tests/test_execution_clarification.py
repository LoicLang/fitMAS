from datetime import date

from fitmas.execution_clarification import build_execution_clarification


def test_execution_clarification_asks_when_uncertainty_changes_recent_week() -> None:
    clarification = build_execution_clarification(
        today=date(2026, 3, 30),
        target_date=date(2026, 3, 29),
        target_session={
            "id": 3,
            "sport_type": "running",
            "scheduled_date": "2026-03-29T07:00:00+01:00",
            "session_title": "Course longue",
            "duration_min": 75,
            "intensity": "moderate",
            "load_score": 4,
            "priority": "High",
            "completion_status": "planned",
        },
        scheduled_sessions=[
            {
                "id": 1,
                "sport_type": "running",
                "scheduled_date": "2026-03-24T07:00:00+01:00",
                "session_title": "Footing",
                "duration_min": 45,
                "intensity": "easy",
                "load_score": 1,
                "priority": "Support",
                "completion_status": "planned",
            },
            {
                "id": 2,
                "sport_type": "swimming",
                "scheduled_date": "2026-03-26T07:00:00+01:00",
                "session_title": "Natation",
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
                "session_title": "Course longue",
                "duration_min": 75,
                "intensity": "moderate",
                "load_score": 4,
                "priority": "High",
                "completion_status": "planned",
            },
        ],
        activities=[
            {
                "id": 11,
                "sport_type": "running",
                "scheduled_session_id": 1,
                "started_at": "2026-03-24T07:02:00+01:00",
                "tss": 40.0,
            }
        ],
    )

    assert clarification is not None
    assert "Tu l'as faite ou pas" in clarification.question
    assert "key_session_salvaged" in clarification.impact_flags


def test_execution_clarification_skips_when_answer_would_not_change_week() -> None:
    clarification = build_execution_clarification(
        today=date(2026, 3, 30),
        target_date=date(2026, 3, 29),
        target_session={
            "id": 3,
            "sport_type": "running",
            "scheduled_date": "2026-03-29T07:00:00+01:00",
            "session_title": "Footing",
            "duration_min": 25,
            "intensity": "easy",
            "load_score": 1,
            "priority": "Support",
            "completion_status": "planned",
        },
        scheduled_sessions=[
            {
                "id": 1,
                "sport_type": "running",
                "scheduled_date": "2026-03-25T07:00:00+01:00",
                "session_title": "Tempo",
                "duration_min": 50,
                "intensity": "moderate",
                "load_score": 3,
                "priority": "High",
                "completion_status": "planned",
            },
            {
                "id": 2,
                "sport_type": "swimming",
                "scheduled_date": "2026-03-27T07:00:00+01:00",
                "session_title": "Natation",
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
                "session_title": "Footing",
                "duration_min": 25,
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
                "tss": 42.0,
            },
            {
                "id": 12,
                "sport_type": "swimming",
                "scheduled_session_id": 2,
                "started_at": "2026-03-27T07:02:00+01:00",
                "tss": 22.0,
            },
        ],
    )

    assert clarification is None


def test_execution_clarification_skips_for_already_skipped_session() -> None:
    clarification = build_execution_clarification(
        today=date(2026, 3, 30),
        target_date=date(2026, 3, 29),
        target_session={
            "id": 3,
            "sport_type": "running",
            "scheduled_date": "2026-03-29T07:00:00+01:00",
            "session_title": "Footing",
            "duration_min": 25,
            "intensity": "easy",
            "load_score": 1,
            "priority": "Support",
            "completion_status": "skipped",
        },
        scheduled_sessions=[],
        activities=[],
    )

    assert clarification is None
