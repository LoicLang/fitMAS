from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import pytz

from fitmas.telegram_scheduler import _daily_target_time, _within_daily_send_window


class TelegramSchedulerTest(unittest.TestCase):
    def test_daily_target_time_is_stable_within_same_day(self) -> None:
        timezone = pytz.timezone("Europe/Paris")
        now = timezone.localize(datetime(2026, 4, 6, 7, 5))
        first = _daily_target_time(now=now, label="morning_briefing", base_hour=7, base_minute=30)
        second = _daily_target_time(
            now=timezone.localize(datetime(2026, 4, 6, 8, 55)),
            label="morning_briefing",
            base_hour=7,
            base_minute=30,
        )

        self.assertEqual(first.hour, second.hour)
        self.assertEqual(first.minute, second.minute)

    def test_daily_target_time_varies_across_days(self) -> None:
        timezone = pytz.timezone("Europe/Paris")
        seen = {
            (
                _daily_target_time(
                    now=timezone.localize(datetime(2026, 4, day, 7, 5)),
                    label="morning_briefing",
                    base_hour=7,
                    base_minute=30,
                ).hour,
                _daily_target_time(
                    now=timezone.localize(datetime(2026, 4, day, 7, 5)),
                    label="morning_briefing",
                    base_hour=7,
                    base_minute=30,
                ).minute,
            )
            for day in range(6, 11)
        }

        self.assertGreater(len(seen), 1)

    def test_within_daily_send_window_only_allows_target_grace_period(self) -> None:
        timezone = pytz.timezone("Europe/Paris")
        anchor = timezone.localize(datetime(2026, 4, 6, 7, 5))
        target = _daily_target_time(
            now=anchor,
            label="morning_briefing",
            base_hour=7,
            base_minute=30,
        )

        self.assertTrue(
            _within_daily_send_window(
                now=target,
                label="morning_briefing",
                base_hour=7,
                base_minute=30,
            )
        )
        self.assertFalse(
            _within_daily_send_window(
                now=target - timedelta(minutes=1),
                label="morning_briefing",
                base_hour=7,
                base_minute=30,
            )
        )
        self.assertFalse(
            _within_daily_send_window(
                now=target + timedelta(minutes=20),
                label="morning_briefing",
                base_hour=7,
                base_minute=30,
            )
        )
