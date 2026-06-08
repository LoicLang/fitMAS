from __future__ import annotations

from datetime import datetime

import pytest

from fitmas.legacy.domain.coaching.generated_week_coherence import (
    GeneratedWeekCoherenceBlocked,
    guard_generated_week_coherence,
)


def test_guard_generated_week_coherence_accepts_valid_review() -> None:
    week = _generated_week()

    result = guard_generated_week_coherence(
        week,
        timezone_name="Europe/Paris",
        now=datetime.fromisoformat("2026-05-04T08:00:00+02:00"),
        request_json_fn=lambda **_kwargs: _review_payload("valid", "commit_original"),
    )

    assert result.week["days"] == week["days"]
    assert result.policy_status == "valid"
    assert result.used_fallback is False
    assert result.review.status == "valid"
    assert [op.operation_type for op in result.patch.operations] == ["create_session", "create_session"]


def test_guard_generated_week_coherence_falls_back_when_review_blocks() -> None:
    week = _generated_week(first_intensity="hard", second_intensity="hard")
    reviews = [
        _review_payload("blocked", "block_original"),
        _review_payload("valid", "commit_original"),
    ]

    result = guard_generated_week_coherence(
        week,
        timezone_name="Europe/Paris",
        now=datetime.fromisoformat("2026-05-04T08:00:00+02:00"),
        request_json_fn=lambda **_kwargs: reviews.pop(0),
    )

    assert result.used_fallback is True
    assert result.policy_status == "valid"
    active_days = [day for day in result.week["days"] if day["sport_type"] != "rest"]
    assert active_days
    assert all(day["intensity"] == "easy" for day in active_days)
    assert all(int(day["load_score"]) <= 1 for day in active_days)
    _assert_no_internal_terms(result.week["summary"])
    assert "charge dure" in result.week["summary"].lower()


def test_guard_generated_week_coherence_falls_back_when_review_requires_confirmation() -> None:
    week = _generated_week(first_intensity="hard", second_intensity="moderate")
    reviews = [
        _review_payload("requires_confirmation", "confirm_original"),
        _review_payload("valid", "commit_original"),
    ]

    result = guard_generated_week_coherence(
        week,
        timezone_name="Europe/Paris",
        now=datetime.fromisoformat("2026-05-04T08:00:00+02:00"),
        request_json_fn=lambda **_kwargs: reviews.pop(0),
    )

    assert result.used_fallback is True
    assert result.policy_status == "valid"
    assert all(day["intensity"] == "easy" for day in result.week["days"] if day["sport_type"] != "rest")
    _assert_no_internal_terms(result.week["summary"])


def test_guard_generated_week_coherence_accepts_non_blocking_fallback() -> None:
    week = _generated_week(first_intensity="hard", second_intensity="hard")
    reviews = [
        _review_payload("blocked", "block_original"),
        _review_payload("requires_confirmation", "confirm_original"),
    ]

    result = guard_generated_week_coherence(
        week,
        timezone_name="Europe/Paris",
        now=datetime.fromisoformat("2026-05-04T08:00:00+02:00"),
        request_json_fn=lambda **_kwargs: reviews.pop(0),
    )

    assert result.used_fallback is True
    assert result.policy_status == "requires_confirmation"
    assert all(day["intensity"] == "easy" for day in result.week["days"] if day["sport_type"] != "rest")
    _assert_no_internal_terms(result.week["summary"])


def test_guard_generated_week_coherence_raises_if_fallback_is_blocked_too() -> None:
    week = _generated_week(first_intensity="hard", second_intensity="hard")

    with pytest.raises(GeneratedWeekCoherenceBlocked):
        guard_generated_week_coherence(
            week,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T08:00:00+02:00"),
            request_json_fn=lambda **_kwargs: _review_payload("blocked", "block_original"),
        )


def _generated_week(*, first_intensity: str = "moderate", second_intensity: str = "easy") -> dict:
    return {
        "intention": "Construire une semaine lisible.",
        "summary": "Deux séances, le reste en marge.",
        "days": [
            _rest_day("monday"),
            _session_day("tuesday", "Footing", first_intensity),
            _rest_day("wednesday"),
            _session_day("thursday", "Velo", second_intensity, sport_type="cycling"),
            _rest_day("friday"),
            _rest_day("saturday"),
            _rest_day("sunday"),
        ],
        "_mesocycle_week": 1,
        "_mesocycle_number": 1,
        "_total_weeks": 1,
    }


def _session_day(day: str, title: str, intensity: str, *, sport_type: str = "running") -> dict:
    load_score = 3 if intensity == "hard" else 2 if intensity == "moderate" else 1
    return {
        "day": day,
        "label": day.capitalize(),
        "sport_type": sport_type,
        "session_type": "tempo" if intensity == "hard" else "easy",
        "session_title": title,
        "session_goal": "Tenir le stimulus.",
        "session_note": "Note.",
        "session_description": "10min easy\n20min steady\n5min easy",
        "duration_min": 45,
        "intensity": intensity,
        "load_score": load_score,
        "priority": "Séance clé" if intensity == "hard" else "Support",
        "nutrition_focus": "",
        "flexibility": "stable",
        "completion_status": "planned",
        "watch_items": [("Charge", "RAS")],
    }


def _rest_day(day: str) -> dict:
    return {
        "day": day,
        "label": day.capitalize(),
        "sport_type": "rest",
        "session_type": "rest",
        "session_title": "Repos",
        "session_goal": "Respirer.",
        "session_note": "Repos.",
        "session_description": "",
        "duration_min": None,
        "intensity": "easy",
        "load_score": 0,
        "priority": "Souplesse",
        "nutrition_focus": "",
        "flexibility": "flexible",
        "completion_status": "planned",
        "watch_items": [("Charge", "RAS")],
    }


def _review_payload(status: str, recommended_policy: str) -> dict:
    severity = "blocked" if status == "blocked" else "info"
    return {
        "status": status,
        "sport_quality": "poor" if status == "blocked" else "good",
        "confidence": 0.8,
        "summary": "Review generated week.",
        "findings": [
            {
                "code": "generated_week_review",
                "severity": severity,
                "detail": "Generated week reviewed.",
                "target_session_ids": [],
            }
        ],
        "suggested_adjustments": [],
        "recommended_policy": recommended_policy,
    }


def _assert_no_internal_terms(text: str) -> None:
    normalized = text.lower()
    forbidden = ("fallback", "review", "reviewer", "patch", "commit")
    for term in forbidden:
        assert term not in normalized
