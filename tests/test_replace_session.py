"""Tests for replace_session mutation."""

from fitmas.plan_actions import _estimate_load_score, _apply_replacement_fields


class FakeSession:
    """Minimal mock for ScheduledSession / DayPlan."""
    def __init__(self, **kwargs):
        defaults = {
            "sport_type": "running",
            "session_type": "intervals",
            "session_title": "Fractionne 8x400m",
            "session_goal": "VMA",
            "session_note": "",
            "session_description": "8x400m allure 10k",
            "duration_min": 55,
            "intensity": "hard",
            "load_score": 5,
            "priority": "Cle",
            "nutrition_focus": "",
            "flexibility": "fixed",
            "completion_status": "planned",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestEstimateLoadScore:
    def test_easy_30min(self):
        assert _estimate_load_score("easy", 30) == 1

    def test_moderate_60min(self):
        assert _estimate_load_score("moderate", 60) == 4

    def test_hard_30min(self):
        assert _estimate_load_score("hard", 30) == 3

    def test_hard_90min(self):
        assert _estimate_load_score("hard", 90) == 9

    def test_none_duration(self):
        assert _estimate_load_score("easy", None) == 0

    def test_zero_duration(self):
        assert _estimate_load_score("easy", 0) == 0

    def test_unknown_intensity(self):
        # Defaults to moderate (2 per 30min)
        assert _estimate_load_score("unknown", 30) == 2


class TestApplyReplacementFields:
    def test_replaces_sport_type(self):
        s = FakeSession()
        _apply_replacement_fields(
            s, new_sport_type="strength", new_session_type="mobility",
            new_duration_min=25, new_intensity="easy",
            new_description="Mobilite epaule", new_title="Mobilite",
            new_goal="Recuperation", rationale="Douleur epaule",
        )
        assert s.sport_type == "strength"
        assert s.session_type == "mobility"
        assert s.duration_min == 25
        assert s.intensity == "easy"
        assert s.session_description == "Mobilite epaule"
        assert s.session_title == "Mobilite"
        assert s.session_goal == "Recuperation"
        assert s.session_note == "Douleur epaule"
        assert s.completion_status == "adapted"

    def test_load_score_recalculated(self):
        s = FakeSession(load_score=5, intensity="hard", duration_min=55)
        _apply_replacement_fields(
            s, new_sport_type=None, new_session_type=None,
            new_duration_min=25, new_intensity="easy",
            new_description=None, new_title=None,
            new_goal=None, rationale=None,
        )
        assert s.load_score == 1  # easy, 25min → 1

    def test_partial_update_keeps_other_fields(self):
        s = FakeSession()
        original_title = s.session_title
        _apply_replacement_fields(
            s, new_sport_type=None, new_session_type=None,
            new_duration_min=None, new_intensity="easy",
            new_description=None, new_title=None,
            new_goal=None, rationale=None,
        )
        assert s.session_title == original_title
        assert s.intensity == "easy"
        assert s.completion_status == "adapted"

    def test_none_fields_are_not_applied(self):
        s = FakeSession(sport_type="running")
        _apply_replacement_fields(
            s, new_sport_type=None, new_session_type=None,
            new_duration_min=None, new_intensity=None,
            new_description=None, new_title=None,
            new_goal=None, rationale=None,
        )
        assert s.sport_type == "running"  # unchanged

    def test_replacement_clears_stale_description_when_sport_changes_without_new_description(self):
        s = FakeSession(
            sport_type="swimming",
            session_type="technique",
            session_description="200m echauffement\n4x100m crawl",
        )
        _apply_replacement_fields(
            s,
            new_sport_type="strength/general",
            new_session_type="training",
            new_duration_min=34,
            new_intensity="moderate",
            new_description=None,
            new_title="Renfo general",
            new_goal="Socle musculaire",
            rationale="Piscine fermee.",
        )

        assert s.sport_type == "strength/general"
        assert s.session_type == "training"
        assert s.session_description == ""


class TestMutationDecisionFields:
    def test_replace_session_fields_exist(self):
        from fitmas.llm import MutationDecision
        d = MutationDecision(
            mutation_type="replace_session",
            target_session_id=42,
            new_sport_type="strength",
            new_session_type="mobility",
            new_duration_min=25,
            new_intensity="easy",
            new_description="Mobilite epaule",
            rationale="Douleur epaule",
            fitmas_message="Adapte.",
        )
        assert d.mutation_type == "replace_session"
        assert d.new_sport_type == "strength"
        assert d.new_duration_min == 25

    def test_replace_session_defaults_to_none(self):
        from fitmas.llm import MutationDecision
        d = MutationDecision(
            mutation_type="no_change",
            rationale="ok",
            fitmas_message="ok",
        )
        assert d.new_sport_type is None
        assert d.new_session_type is None
        assert d.new_duration_min is None
        assert d.new_intensity is None
        assert d.new_description is None
