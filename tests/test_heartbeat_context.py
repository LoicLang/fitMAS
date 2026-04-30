"""Tests for the heartbeat context bundle.

Covers the 2026-04-29 incident scenario explicitly: yesterday's running
activity was linked to a planned session, but the heartbeat claimed
"hier t'as sorti du offplan" because the prompt mixed yesterday-specific
context with the 7d offplan aggregate. The new structured truth bundle
makes that conflation impossible at the prompt layer.
"""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from fitmas.recent_reality import RecentRealityWindow
from fitmas.skills.heartbeat.context import (
    HeartbeatCapabilityBudget,
    build_heartbeat_context_bundle,
    render_heartbeat_context_bundle,
)


def _planned(
    *,
    session_id: int,
    sport: str,
    title: str = "Session",
    duration_min: int = 30,
    status: str = "planned",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        sport_type=sport,
        session_title=title,
        duration_min=duration_min,
        completion_status=status,
    )


def _activity(
    *,
    activity_id: int,
    sport: str,
    duration_min: int,
    scheduled_session_id: int | None,
    started_at: date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=activity_id,
        sport_type=sport,
        duration_min=duration_min,
        scheduled_session_id=scheduled_session_id,
        started_at=started_at,
        created_at=started_at,
    )


def _reality(
    *,
    planned: int = 4,
    confirmed: int = 1,
    claimed: int = 0,
    missed_streak_days: int = 0,
) -> RecentRealityWindow:
    return RecentRealityWindow(
        planned_sessions_7d=planned,
        confirmed_sessions_7d=confirmed,
        claimed_sessions_7d=claimed,
        key_sessions_salvaged_7d=0,
        planned_tss_7d=0.0,
        observed_tss_7d=0.0,
        missed_streak_days=missed_streak_days,
    )


class HeartbeatCapabilityBudgetTest(unittest.TestCase):
    def test_default_is_read_only_with_no_mutation(self) -> None:
        budget = HeartbeatCapabilityBudget()
        self.assertTrue(budget.read_only)
        self.assertTrue(budget.can_emit_message)
        self.assertFalse(budget.can_emit_plan_patch)
        self.assertFalse(budget.can_emit_candidate)


class YesterdayTruthStatusTest(unittest.TestCase):
    def test_status_planned_done_when_all_planned_sessions_linked(self) -> None:
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="strength"),
            yesterday_planned_sessions=[_planned(session_id=37, sport="running")],
            yesterday_activities=[
                _activity(
                    activity_id=40, sport="running", duration_min=32,
                    scheduled_session_id=37, started_at=date(2026, 4, 28),
                ),
            ],
            yesterday_claims=(),
            week_recent_reality=_reality(),
            week_activities=(),
        )
        self.assertEqual(bundle.yesterday.status, "planned_done")
        self.assertTrue(bundle.yesterday.linked_to_plan)
        self.assertEqual(bundle.yesterday.linked_activity_count, 1)
        self.assertEqual(bundle.yesterday.offplan_activity_count, 0)

    def test_status_offplan_done_when_no_plan_but_activity(self) -> None:
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="strength"),
            yesterday_planned_sessions=(),
            yesterday_activities=[
                _activity(
                    activity_id=41, sport="cycling", duration_min=45,
                    scheduled_session_id=None, started_at=date(2026, 4, 28),
                ),
            ],
            yesterday_claims=(),
            week_recent_reality=_reality(),
            week_activities=(),
        )
        self.assertEqual(bundle.yesterday.status, "offplan_done")
        self.assertFalse(bundle.yesterday.linked_to_plan)

    def test_status_planned_partial_when_one_session_done_one_missed(self) -> None:
        """Two planned sessions yesterday, only one linked to a real activity.
        Status reflects the partial completion, but the per-session detail
        tells the LLM exactly which one is missing."""
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="rest"),
            yesterday_planned_sessions=[
                _planned(session_id=37, sport="running"),
                _planned(session_id=38, sport="strength"),
            ],
            yesterday_activities=[
                _activity(
                    activity_id=40, sport="running", duration_min=32,
                    scheduled_session_id=37, started_at=date(2026, 4, 28),
                ),
            ],
            yesterday_claims=(),
            week_recent_reality=_reality(),
            week_activities=(),
        )
        self.assertEqual(bundle.yesterday.status, "planned_partial")

    def test_status_planned_missed_when_planned_but_no_link(self) -> None:
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="rest"),
            yesterday_planned_sessions=[_planned(session_id=37, sport="swimming")],
            yesterday_activities=(),
            yesterday_claims=(),
            week_recent_reality=_reality(),
            week_activities=(),
        )
        self.assertEqual(bundle.yesterday.status, "planned_missed")

    def test_status_rest_when_only_rest_planned_and_no_activity(self) -> None:
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="running"),
            yesterday_planned_sessions=[_planned(session_id=37, sport="rest")],
            yesterday_activities=(),
            yesterday_claims=(),
            week_recent_reality=_reality(),
            week_activities=(),
        )
        self.assertEqual(bundle.yesterday.status, "rest")


class WeekDigestTest(unittest.TestCase):
    def test_offplan_sessions_filter_to_unlinked_within_window(self) -> None:
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=10, sport="rest"),
            yesterday_planned_sessions=(),
            yesterday_activities=(),
            yesterday_claims=(),
            week_recent_reality=_reality(planned=4, confirmed=1, claimed=0),
            week_activities=[
                _activity(
                    activity_id=40, sport="running", duration_min=32,
                    scheduled_session_id=37, started_at=date(2026, 4, 28),
                ),
                _activity(
                    activity_id=41, sport="cycling", duration_min=45,
                    scheduled_session_id=None, started_at=date(2026, 4, 23),
                ),
                _activity(
                    activity_id=42, sport="running", duration_min=28,
                    scheduled_session_id=None, started_at=date(2026, 4, 26),
                ),
                # Outside the 7d window — must be ignored
                _activity(
                    activity_id=43, sport="swimming", duration_min=60,
                    scheduled_session_id=None, started_at=date(2026, 4, 1),
                ),
            ],
        )
        self.assertEqual(bundle.week.offplan_count, 2)
        self.assertEqual(
            tuple((fact.occurred_on, fact.sport, fact.duration_min) for fact in bundle.week.offplan_sessions),
            (
                (date(2026, 4, 23), "cycling", 45),
                (date(2026, 4, 26), "running", 28),
            ),
        )


class IncidentScenarioTest(unittest.TestCase):
    """The exact 2026-04-29 morning incident."""

    def test_yesterday_linked_separated_from_week_offplan_aggregate(self) -> None:
        """Yesterday running activity linked to plan, AND 2 offplan sorties
        elsewhere in the week. The prompt must declare YesterdayTruth.linked_to_plan
        as `oui` and the WeekDigest offplan as `2`, distinctly — so the LLM
        cannot project the weekly offplan count onto yesterday."""
        today = date(2026, 4, 29)
        bundle = build_heartbeat_context_bundle(
            today=today,
            today_planned_session=_planned(session_id=38, sport="strength", duration_min=34),
            yesterday_planned_sessions=[
                _planned(session_id=37, sport="running", title="Tempo", duration_min=30),
            ],
            yesterday_activities=[
                _activity(
                    activity_id=40, sport="running", duration_min=32,
                    scheduled_session_id=37, started_at=date(2026, 4, 28),
                ),
            ],
            yesterday_claims=(),
            week_recent_reality=_reality(planned=4, confirmed=1, claimed=0),
            week_activities=[
                _activity(
                    activity_id=40, sport="running", duration_min=32,
                    scheduled_session_id=37, started_at=date(2026, 4, 28),
                ),
                _activity(
                    activity_id=41, sport="cycling", duration_min=45,
                    scheduled_session_id=None, started_at=date(2026, 4, 23),
                ),
                _activity(
                    activity_id=42, sport="running", duration_min=28,
                    scheduled_session_id=None, started_at=date(2026, 4, 26),
                ),
            ],
        )

        rendered = render_heartbeat_context_bundle(bundle)

        # Yesterday is unambiguously linked-to-plan
        self.assertIn("[YesterdayTruth", rendered)
        self.assertIn("linked_to_plan: oui", rendered)
        self.assertIn("status: planned_done", rendered)

        # WeekDigest is a separate, explicitly-labelled aggregate block
        self.assertIn("[WeekDigest", rendered)
        self.assertIn("agregat hebdo, NE PAS appliquer a un jour", rendered)
        self.assertIn("offplan: 2", rendered)

        # Today is its own block
        self.assertIn("[TodayTruth", rendered)
        self.assertIn("strength", rendered)


if __name__ == "__main__":
    unittest.main()
