from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from fitmas.recent_reality import RecentRealityWindow
from fitmas.skills.heartbeat.context import (
    build_heartbeat_context_bundle,
    render_heartbeat_context_bundle,
)


def _recent_reality() -> RecentRealityWindow:
    return RecentRealityWindow(
        planned_sessions_7d=2,
        confirmed_sessions_7d=1,
        claimed_sessions_7d=0,
        key_sessions_salvaged_7d=0,
        planned_tss_7d=60.0,
        observed_tss_7d=30.0,
        missed_streak_days=0,
    )


def test_heartbeat_bundle_renders_future_plan_window_truth() -> None:
    friday_session = SimpleNamespace(
        id=46,
        scheduled_date=datetime(2026, 5, 8, 18, 0),
        day="friday",
        sport_type="running",
        session_type="easy",
        session_title="Footing Z2",
        duration_min=40,
        completion_status="adapted",
    )

    bundle = build_heartbeat_context_bundle(
        today=date(2026, 5, 7),
        today_planned_session=None,
        yesterday_planned_sessions=[],
        yesterday_activities=[],
        yesterday_claims=[],
        week_recent_reality=_recent_reality(),
        week_activities=[],
        future_scheduled_sessions=[friday_session],
    )

    rendered = render_heartbeat_context_bundle(bundle)

    assert "[PlanWindowTruth" in rendered
    assert "2026-05-08 (vendredi)" in rendered
    assert "running" in rendered
    assert "40min" in rendered
    assert "[adapted]" in rendered
