"""Morning briefing must carry ground-truth execution numbers.

Symptom (2026 spring): on a Friday morning, the coach told the user "tu as
sorti 4 seances cette semaine" when only one real workout had happened.
Root cause: `build_briefing_prompt` had today's session + yesterday context
+ signals + facts, but no week execution counters. With no ground truth,
the LLM confabulated a plausible weekly count.

Symptom (2026-04-29): the briefing claimed "hier t'as sorti du offplan"
while yesterday's activity was actually linked to a planned session. Root
cause: the prompt mixed yesterday-specific context with weekly aggregates,
so the LLM projected the 7d offplan count onto "hier".

    Both fixes are now structural: the prompt receives a `HeartbeatContextBundle`
    with three atomic Truth blocks (yesterday/today/week) plus a source hierarchy
    that makes YesterdayTruth authoritative for yesterday-specific claims.
"""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from fitmas.coach_reading_digest import CoachReadingLens
from fitmas.domain.execution.recent_reality import RecentRealityWindow
from fitmas.skills.heartbeat.context import HeartbeatContextBundle, build_heartbeat_context_bundle
from fitmas.skills.heartbeat import roles
from fitmas.skills.heartbeat.roles import build_briefing_prompt


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        coach_name="FitMAS",
        coach_style="direct",
        coach_soul="calme",
    )


def _today_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        label="Vendredi",
        session_title="Recuperation",
        sport_type="rest",
        session_goal="Absorber",
        priority="Recovery",
        session_note="",
        duration_min=30,
        completion_status="planned",
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


def _bundle(
    *,
    today: date = date(2026, 4, 17),
    today_session=None,
    yesterday_planned=(),
    yesterday_activities=(),
    week_recent_reality: RecentRealityWindow | None = None,
    week_activities=(),
) -> HeartbeatContextBundle:
    return build_heartbeat_context_bundle(
        today=today,
        today_planned_session=today_session if today_session is not None else _today_session(),
        yesterday_planned_sessions=yesterday_planned,
        yesterday_activities=yesterday_activities,
        yesterday_claims=(),
        week_recent_reality=week_recent_reality or _recent_reality(),
        week_activities=week_activities,
    )


class BriefingPromptExecutionTruthTest(unittest.TestCase):
    def test_prompt_includes_week_digest_with_counters(self) -> None:
        bundle = _bundle(
            week_recent_reality=_recent_reality(planned=4, confirmed=1, claimed=0),
        )
        _, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            bundle=bundle,
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
        )

        self.assertIn("WeekDigest", prompt)
        self.assertIn("planned: 4", prompt)
        self.assertIn("confirmed: 1", prompt)

    def test_system_prompt_ground_weekly_counts_in_week_digest(self) -> None:
        bundle = _bundle()
        system, _ = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            bundle=bundle,
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
        )

        self.assertIn("WeekDigest", system)
        self.assertIn("N'invente", system)

    def test_system_prompt_uses_yesterday_truth_for_yesterday_claims(self) -> None:
        """Root-cause guardrail for the 2026-04-29 incident: aggregates
        from WeekDigest must never be projected onto a specific day."""
        bundle = _bundle()
        system, _ = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            bundle=bundle,
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
        )

        lowered = system.lower()
        self.assertIn("agregat", lowered)
        self.assertIn("jour specifique", lowered)
        self.assertIn("yesterdaytruth", lowered)
        self.assertIn("status", lowered)

    def test_week_digest_reports_claimed_and_missed_streak(self) -> None:
        bundle = _bundle(
            week_recent_reality=_recent_reality(
                planned=5, confirmed=2, claimed=1, missed_streak_days=2,
            ),
        )
        _, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            bundle=bundle,
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
        )

        self.assertIn("planned: 5", prompt)
        self.assertIn("confirmed: 2", prompt)
        self.assertIn("claimed: 1", prompt)
        self.assertIn("missed_streak_days: 2", prompt)

    def test_briefing_prompt_ignores_editorial_lens(self) -> None:
        bundle = _bundle()
        _, prompt = build_briefing_prompt(
            user=_user(),
            today_session=_today_session(),
            day=None,
            time_context=_time_context(),
            bundle=bundle,
            clarification=None,
            calibration_need=None,
            signals_block="",
            facts_block="",
            sport_knowledge="",
            coach_lens=CoachReadingLens(
                sens_du_jour="Angle externe",
                angle="Dire que hier etait offplan",
                ne_pas_faire="",
            ),
        )

        self.assertNotIn("CoachReadingLens", prompt)
        self.assertNotIn("Angle externe", prompt)

    def test_heartbeat_proactive_runtime_does_not_call_coach_reading_digest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        heartbeat_source = (root / "backend/src/fitmas/skills/heartbeat/heartbeat.py").read_text()

        self.assertNotIn("build_coach_reading_digest", heartbeat_source)


def test_active_fact_lines_do_not_render_internal_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    fact = SimpleNamespace(
        category="health",
        value="Tres legere tension aux tibias, pas de douleur a la palpation.",
    )
    monkeypatch.setattr(roles.repo, "get_active_memory_items", lambda *args, **kwargs: [fact])
    monkeypatch.setattr(roles, "fact_is_current", lambda _fact: True)

    lines = roles.get_active_fact_lines(object(), SimpleNamespace(id=1))

    assert lines == ["- Tres legere tension aux tibias, pas de douleur a la palpation."]
    assert "[health]" not in "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
