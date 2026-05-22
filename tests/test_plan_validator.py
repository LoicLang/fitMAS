from __future__ import annotations

import unittest
from datetime import date

from fitmas.domain.planning.validator import validate_week_plan
from fitmas.domain.planning.planning_decision import PlanningDecision


class PlanValidatorTest(unittest.TestCase):
    def test_validator_accepts_balanced_week(self) -> None:
        days = [
            _day("monday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("tuesday", "running", "intervals", 55, "hard", 3, "Seance cle"),
            _day("wednesday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("thursday", "cycling", "endurance", 75, "moderate", 2, "Support"),
            _day("friday", "strength", "core", 30, "easy", 1, "Support"),
            _day("saturday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("sunday", "running", "long", 75, "moderate", 3, "Repere fort"),
        ]

        result = validate_week_plan(days, primary_sport="running")

        self.assertTrue(result.is_valid)

    def test_validator_rejects_adjacent_hard_sessions(self) -> None:
        decision = PlanningDecision(
            user_id=1,
            week_start=date(2026, 3, 23),
            decision_version="v1",
            planning_mode="maintain_load",
            adaptation_level="none",
            adaptation_scope="week",
            weekly_target_tss=250.0,
            intensity_distribution="balanced",
            key_session_count=2,
            strength_session_count=1,
            long_session=True,
            rationale=("test",),
            adaptations=("test",),
            risk_flags=(),
        )
        days = [
            _day("monday", "running", "intervals", 55, "hard", 3, "Seance cle"),
            _day("tuesday", "cycling", "intervals", 70, "hard", 3, "Seance cle"),
            _day("wednesday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("thursday", "running", "easy", 40, "easy", 1, "Support"),
            _day("friday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("saturday", "rest", "rest", None, "easy", 0, "Souplesse"),
            _day("sunday", "running", "long", 70, "moderate", 3, "Repere fort"),
        ]

        result = validate_week_plan(days, primary_sport="running", planning_decision=decision)

        self.assertFalse(result.is_valid)
        self.assertTrue(any(issue.code == "adjacent_hard_sessions" for issue in result.issues))


def _day(day: str, sport_type: str, session_type: str, duration_min: int | None, intensity: str, load_score: int, priority: str) -> dict:
    return {
        "day": day,
        "label": day.capitalize(),
        "sport_type": sport_type,
        "session_type": session_type,
        "session_title": f"{sport_type} {session_type}",
        "session_goal": "test",
        "session_note": "",
        "session_description": "",
        "duration_min": duration_min,
        "intensity": intensity,
        "load_score": load_score,
        "priority": priority,
        "nutrition_focus": "",
        "flexibility": "stable",
        "completion_status": "planned",
        "change_notes": [],
        "watch_items": [("watch", "detail")],
    }


if __name__ == "__main__":
    unittest.main()
