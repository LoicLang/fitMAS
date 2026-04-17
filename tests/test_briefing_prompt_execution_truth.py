"""Morning briefing must carry ground-truth execution numbers.

Symptom: on a Friday morning, the coach told the user "tu as sorti 4
seances cette semaine" when only one real workout had happened. Root
cause: `build_briefing_prompt` passed today's session + yesterday
context + signals + facts, but never the week execution counters from
`recent_reality`. With no ground truth, the LLM confabulated a plausible
weekly count.

Fix A: inject a structured "Execution reelle semaine" block carrying
the counters from `RecentRealityWindow`, and add an explicit system-
prompt rule forbidding invention of weekly counts.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.recent_reality import RecentRealityWindow
from fitmas.skills.heartbeat.roles import build_briefing_prompt


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        coach_name="FitMAS",
        coach_style="direct",
        coach_soul="calme",
    )


def _today_session() -> SimpleNamespace:
    return SimpleNamespace(
        label="Vendredi",
        session_title="Recuperation",
        sport_type="rest",
        session_goal="Absorber",
        priority="Recovery",
        session_note="",
    )


def _time_context() -> dict[str, str]:
    return {
        "timezone": "Europe/Paris",
        "day_key": "friday",
        "day_label": "Vendredi",
        "day_label_fr": "vendredi",
        "date_iso": "2026-04-17",
        "date_fr": "17 avril 2026",
        "time_label": "07:30",
        "time_fr": "07:30",
        "now_iso": "2026-04-17T07:30:00+02:00",
        "part_of_day": "matin",
    }


def _recent_reality(
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


class BriefingPromptExecutionTruthTest(unittest.TestCase):
    def test_prompt_includes_execution_truth_block_with_counters(self) -> None:
        system, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            yesterday_context="",
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
            recent_reality=_recent_reality(planned=4, confirmed=1, claimed=0),
        )

        self.assertIn("Execution reelle semaine", prompt)
        self.assertIn("4", prompt)
        self.assertIn("1", prompt)
        self.assertIn("planifiees", prompt.lower())
        self.assertIn("confirmees", prompt.lower())

    def test_system_prompt_forbids_invented_weekly_counts(self) -> None:
        system, _ = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            yesterday_context="",
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
            recent_reality=_recent_reality(),
        )

        # The rule must be present unconditionally so it applies even
        # when recent_reality is omitted (defense in depth).
        self.assertIn("Execution reelle semaine", system)
        self.assertIn("N'invente", system)

    def test_system_prompt_forbids_invented_counts_even_without_reality_block(self) -> None:
        """Even when `recent_reality` isn't passed (legacy callers), the
        LLM must be instructed not to make up weekly counts."""
        system, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            yesterday_context="",
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
            # no recent_reality kwarg
        )

        self.assertIn("N'invente", system)
        self.assertNotIn("Execution reelle semaine", prompt)

    def test_execution_block_reports_claimed_and_missed_streak(self) -> None:
        _, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            yesterday_context="",
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
            recent_reality=_recent_reality(planned=5, confirmed=2, claimed=1, missed_streak_days=2),
        )

        self.assertIn("2", prompt)  # confirmed
        self.assertIn("5", prompt)  # planned
        self.assertIn("revendiqu", prompt.lower())


if __name__ == "__main__":
    unittest.main()
