from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from fitmas.legacy.decision.grounding import (
    ReplyGroundingPacket,
    plan_window_facts_from_sessions,
    render_grounding_packet_for_prompt,
    resolve_temporal_intents,
)


def test_resolve_typed_temporal_references_without_user_text_parsing() -> None:
    resolved = resolve_temporal_intents(
        (
            {"kind": "relative_day", "value": "tomorrow", "role": "source"},
            {"kind": "weekday", "value": "friday", "role": "target"},
        ),
        local_date=date(2026, 5, 6),
    )

    assert resolved["source"][0].resolved_date == date(2026, 5, 7)
    assert resolved["source"][0].day_label == "jeudi"
    assert resolved["target"][0].resolved_date == date(2026, 5, 8)
    assert resolved["target"][0].day_label == "vendredi"


def test_plan_window_facts_render_future_truth_with_day_and_status() -> None:
    sessions = [
        SimpleNamespace(
            id=46,
            scheduled_date=datetime(2026, 5, 8, 18, 0),
            day="friday",
            sport_type="running",
            session_type="easy",
            session_title="Footing Z2",
            duration_min=40,
            intensity="easy",
            completion_status="adapted",
        )
    ]

    facts = plan_window_facts_from_sessions(sessions)
    packet = ReplyGroundingPacket(
        local_date=date(2026, 5, 7),
        timezone_name="Europe/Paris",
        plan_window=facts,
    )

    rendered = "\n".join(render_grounding_packet_for_prompt(packet))

    assert "2026-05-08 (vendredi)" in rendered
    assert "running" in rendered
    assert "40min" in rendered
    assert "[adapted]" in rendered
