from __future__ import annotations

from datetime import datetime

from fitmas import api_messages
from fitmas.conversation_context import build_conversation_context


def test_future_session_confirmation_reply_keeps_tomorrow_session() -> None:
    context = build_conversation_context(
        user_text="Mais demain piscine sans faute j'y serai",
        conversation_history=[],
        timezone_name="Europe/Paris",
        scheduled_sessions=[
            {
                "id": 12,
                "day": "thursday",
                "scheduled_date": datetime.fromisoformat("2026-04-09T07:00:00+02:00"),
                "sport_type": "swimming",
                "session_title": "Natation technique",
                "completion_status": "planned",
            }
        ],
        activities=[],
        active_facts=[],
        now=datetime.fromisoformat("2026-04-08T08:13:00+02:00"),
    )

    reply = api_messages._maybe_future_session_confirmation_reply(
        user_text="Mais demain piscine sans faute j'y serai",
        conversation_context=context,
        scheduled_sessions=[
            {
                "id": 12,
                "day": "thursday",
                "scheduled_date": datetime.fromisoformat("2026-04-09T07:00:00+02:00"),
                "sport_type": "swimming",
                "session_title": "Natation technique",
                "completion_status": "planned",
            }
        ],
        timezone_name="Europe/Paris",
    )

    assert reply is not None
    assert "natation technique" in reply.lower()
    assert "comme prevu" in reply.lower()
    assert "vendredi" not in reply.lower()


def test_future_session_confirmation_reply_anchors_explicit_day() -> None:
    context = build_conversation_context(
        user_text="Non laisse la piscine demain, on est jeudi demain",
        conversation_history=[],
        timezone_name="Europe/Paris",
        scheduled_sessions=[
            {
                "id": 12,
                "day": "thursday",
                "scheduled_date": datetime.fromisoformat("2026-04-09T07:00:00+02:00"),
                "sport_type": "swimming",
                "session_title": "Natation technique",
                "completion_status": "planned",
            }
        ],
        activities=[],
        active_facts=[],
        now=datetime.fromisoformat("2026-04-08T08:14:00+02:00"),
    )

    reply = api_messages._maybe_future_session_confirmation_reply(
        user_text="Non laisse la piscine demain, on est jeudi demain",
        conversation_context=context,
        scheduled_sessions=[
            {
                "id": 12,
                "day": "thursday",
                "scheduled_date": datetime.fromisoformat("2026-04-09T07:00:00+02:00"),
                "sport_type": "swimming",
                "session_title": "Natation technique",
                "completion_status": "planned",
            }
        ],
        timezone_name="Europe/Paris",
    )

    assert reply is not None
    assert "aujourd'hui c'est mercredi 8 avril" in reply.lower()
    assert "demain, c'est jeudi 9 avril" in reply.lower()
    assert "natation technique" in reply.lower()
