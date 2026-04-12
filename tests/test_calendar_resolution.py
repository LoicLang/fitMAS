from __future__ import annotations

from datetime import date, datetime

from fitmas.calendar_resolution import build_session_item, resolve_calendar_payload


def test_past_unfinished_session_becomes_missing() -> None:
    session = {
        "id": 1,
        "day": "monday",
        "label": "Lundi",
        "scheduled_date": "2026-03-23",
        "sport_type": "running",
        "session_type": "easy_run",
        "session_title": "Footing facile",
        "session_goal": "Souple",
        "session_description": "",
        "duration_min": 45,
        "load_band": "easy",
        "priority": "Normal",
        "completion_status": "planned",
    }

    resolved = build_session_item(session, [], today=date(2026, 3, 28))

    assert resolved["status"] == "missing"
    assert resolved["display_date"] == "2026-03-23"


def test_past_adapted_session_without_activity_becomes_missing() -> None:
    session = {
        "id": 3,
        "day": "friday",
        "label": "Vendredi",
        "scheduled_date": "2026-04-10",
        "sport_type": "swimming",
        "session_type": "technique",
        "session_title": "Natation technique",
        "session_goal": "Nager propre",
        "session_description": "",
        "duration_min": 36,
        "load_band": "easy",
        "priority": "Support",
        "completion_status": "adapted",
    }

    resolved = build_session_item(session, [], today=date(2026, 4, 12))

    assert resolved["status"] == "missing"
    assert resolved["completion_status"] == "adapted"


def test_wrong_sport_linked_activity_stays_offplan() -> None:
    session = {
        "id": 2,
        "day": "friday",
        "label": "Vendredi",
        "scheduled_date": "2026-03-27",
        "sport_type": "running",
        "session_type": "tempo",
        "session_title": "Tempo",
        "session_goal": "Tenir l'allure",
        "session_description": "",
        "duration_min": 50,
        "load_band": "moderate",
        "priority": "Cle",
        "completion_status": "planned",
    }
    activity = {
        "id": 91,
        "scheduled_session_id": 2,
        "sport_type": "cycling",
        "title": "Sortie vélo off-plan",
        "duration_min": 75,
        "perceived_load": 4,
        "started_at": datetime(2026, 3, 27, 8, 0),
        "source": "manual",
    }

    payload = resolve_calendar_payload(
        scheduled_sessions=[session],
        activities=[activity],
        today=date(2026, 3, 28),
    )

    assert payload["sessions"][0]["status"] == "missing"
    assert payload["sessions"][0]["has_invalid_linked_activity"] is True
    assert payload["offplan"][0]["status"] == "offplan"
    assert payload["offplan"][0]["title"] == "Sortie vélo off-plan"
