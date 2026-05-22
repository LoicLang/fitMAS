"""Streak signal must filter out short/casual activities.

The LLM reads `signals_block` in the morning briefing and morning
heartbeat, and a noisy streak signal ("4 seances consecutives
realisees") makes the coach confabulate "tu as sorti 4 seances cette
semaine" when the user only did one real workout and a few short walks.

Fix C: only count activities with a known duration >= 20 min, OR with
unknown duration (can't tell, stay conservative on claims that don't
specify). Walks/commute rides under the threshold no longer inflate the
streak.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-streak-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.signals import collect_signals
from fitmas.core.time_context import DAY_KEYS, day_label_fr, get_local_now


def _plan_day(day_key: str) -> dict:
    return {
        "day": day_key,
        "label": day_label_fr(day_key, capitalize=True),
        "sport_type": "running",
        "session_type": "easy",
        "session_title": "Footing",
        "session_goal": "Bouger",
        "session_note": "",
        "session_description": "",
        "duration_min": 40,
        "intensity": "easy",
        "load_score": 1,
        "priority": "Normal",
        "nutrition_focus": "",
        "flexibility": "stable",
        "completion_status": "planned",
    }


class StreakSignalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris", coach_name="FitMAS", coach_style="direct")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        now = get_local_now(self.user.timezone)
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[_plan_day(DAY_KEYS[now.weekday()])],
        )

    def tearDown(self) -> None:
        self.db.close()

    def _add_activity(self, *, days_ago: int, duration_min: int | None, sport_type: str = "running") -> None:
        now = get_local_now(self.user.timezone)
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="strava",
            sport_type=sport_type,
            title=f"Activity {days_ago}d",
            duration_min=duration_min,
            distance_m=None,
            elevation_m=None,
            perceived_load=None,
            note="",
            started_at=now - timedelta(days=days_ago),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=None,
        )

    def test_short_walks_do_not_fire_streak(self) -> None:
        """Four consecutive days of 10-15min walks must NOT produce a streak
        signal — under the fix, a streak requires substantive activities
        (>= 20 min), not strolls or commute rides."""
        for offset in (1, 2, 3, 4):
            self._add_activity(days_ago=offset, duration_min=12)

        kinds = {signal["kind"] for signal in collect_signals(self.db, self.user)}

        self.assertNotIn("streak", kinds)

    def test_substantive_runs_fire_streak(self) -> None:
        """Three consecutive days of 30min+ runs produce the streak signal."""
        for offset in (1, 2, 3):
            self._add_activity(days_ago=offset, duration_min=30)

        signals = collect_signals(self.db, self.user)
        streak = next((s for s in signals if s["kind"] == "streak"), None)

        self.assertIsNotNone(streak, f"expected streak signal, got {[s['kind'] for s in signals]}")
        self.assertEqual(streak["data"]["streak"], 3)

    def test_mixed_walks_and_runs_counts_only_substantive_days(self) -> None:
        """1 real run yesterday + 3 short walks before must not roll into
        a 4-day streak; the walks are filtered out so the run is alone."""
        self._add_activity(days_ago=1, duration_min=36)  # real run
        for offset in (2, 3, 4):
            self._add_activity(days_ago=offset, duration_min=10)

        kinds = {signal["kind"] for signal in collect_signals(self.db, self.user)}

        self.assertNotIn("streak", kinds)

    def test_streak_breaks_when_only_short_activity_between_substantive_days(self) -> None:
        """Run 4d ago, walk 3d ago, run 2d ago, run 1d ago -> streak is 2
        (the walk 3d ago breaks the chain), not 4."""
        self._add_activity(days_ago=1, duration_min=35)
        self._add_activity(days_ago=2, duration_min=40)
        self._add_activity(days_ago=3, duration_min=8)  # walk
        self._add_activity(days_ago=4, duration_min=32)

        signals = collect_signals(self.db, self.user)
        streak = next((sig for sig in signals if sig["kind"] == "streak"), None)

        # 1d + 2d ago count, 3d ago (walk) breaks -> streak=2, below threshold (3)
        self.assertIsNone(streak)


if __name__ == "__main__":
    unittest.main()
