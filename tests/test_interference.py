"""Tests for multisport interference matrix."""

from fitmas.domain.planning.interference import check_adjacent_conflicts, format_conflicts_for_prompt


def _session(sport_type="running", intensity="moderate"):
    return {"sport_type": sport_type, "intensity": intensity}


class TestCheckAdjacentConflicts:
    def test_no_conflict_easy_sessions(self):
        sessions = [_session("running", "easy"), _session("cycling", "easy")]
        assert check_adjacent_conflicts(sessions) == []

    def test_hard_running_hard_running_avoid(self):
        sessions = [_session("running", "hard"), _session("running", "hard")]
        conflicts = check_adjacent_conflicts(sessions)
        assert len(conflicts) == 1
        assert conflicts[0][2].level == "avoid"

    def test_hard_strength_hard_running_avoid(self):
        sessions = [_session("strength", "hard"), _session("running", "hard")]
        conflicts = check_adjacent_conflicts(sessions)
        assert len(conflicts) == 1
        assert conflicts[0][2].level == "avoid"

    def test_hard_climbing_hard_strength_avoid(self):
        sessions = [_session("climbing", "hard"), _session("strength", "hard")]
        conflicts = check_adjacent_conflicts(sessions)
        assert len(conflicts) == 1
        assert conflicts[0][2].level == "avoid"

    def test_swimming_no_conflict(self):
        sessions = [_session("swimming", "hard"), _session("running", "hard")]
        assert check_adjacent_conflicts(sessions) == []

    def test_rest_day_no_conflict(self):
        sessions = [_session("running", "hard"), _session("rest", "easy"), _session("running", "hard")]
        # rest in middle breaks the chain
        assert check_adjacent_conflicts(sessions) == []

    def test_moderate_strength_hard_running_mild(self):
        sessions = [_session("strength", "moderate"), _session("running", "hard")]
        conflicts = check_adjacent_conflicts(sessions)
        assert len(conflicts) == 1
        assert conflicts[0][2].level == "mild"

    def test_multiple_conflicts(self):
        sessions = [
            _session("running", "hard"),
            _session("running", "hard"),
            _session("rest"),
            _session("climbing", "hard"),
            _session("strength", "hard"),
        ]
        conflicts = check_adjacent_conflicts(sessions)
        assert len(conflicts) == 2

    def test_three_sessions(self):
        sessions = [
            _session("strength", "hard"),
            _session("running", "hard"),
            _session("cycling", "easy"),
        ]
        conflicts = check_adjacent_conflicts(sessions)
        # Only strength→running conflict
        assert len(conflicts) == 1


class TestFormatConflicts:
    def test_empty(self):
        assert format_conflicts_for_prompt([]) == ""

    def test_formats_conflict(self):
        sessions = [_session("running", "hard"), _session("running", "hard")]
        conflicts = check_adjacent_conflicts(sessions)
        text = format_conflicts_for_prompt(conflicts)
        assert "running" in text
        assert "avoid" in text
