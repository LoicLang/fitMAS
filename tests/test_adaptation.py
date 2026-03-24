"""Tests for the adaptation module triggers and response parsing."""

from fitmas.adaptation import (
    AdaptationTrigger,
    _HIGH_URGENCY_KEYWORDS,
    _parse_adaptation_response,
)


class TestHighUrgencyKeywords:
    def test_douleur_is_high(self):
        assert "douleur" in _HIGH_URGENCY_KEYWORDS

    def test_fatigue_is_high(self):
        assert "fatigue" in _HIGH_URGENCY_KEYWORDS

    def test_blessure_is_high(self):
        assert "blessure" in _HIGH_URGENCY_KEYWORDS


class TestParseAdaptationResponse:
    def test_empty_response(self):
        decisions, msg = _parse_adaptation_response(None)
        assert decisions == []
        assert msg == ""

    def test_no_adaptations(self):
        decisions, msg = _parse_adaptation_response({"adaptations": [], "message": "Tout va bien."})
        assert decisions == []
        assert msg == "Tout va bien."

    def test_keep_action_is_skipped(self):
        data = {
            "adaptations": [
                {"session_id": 1, "action": "keep", "rationale": "Pas impacte"}
            ],
            "message": "ok",
        }
        decisions, msg = _parse_adaptation_response(data)
        assert len(decisions) == 0

    def test_replace_action(self):
        data = {
            "adaptations": [
                {
                    "session_id": 42,
                    "action": "replace",
                    "new_sport_type": "strength",
                    "new_session_type": "mobility",
                    "new_duration_min": 25,
                    "new_intensity": "easy",
                    "new_description": "Mobilite epaule",
                    "new_title": "Mobilite",
                    "rationale": "Douleur epaule signalee",
                }
            ],
            "message": "J'ai adapte ta seance.",
        }
        decisions, msg = _parse_adaptation_response(data)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.mutation_type == "replace_session"
        assert d.target_session_id == 42
        assert d.new_sport_type == "strength"
        assert d.new_session_type == "mobility"
        assert d.new_duration_min == 25
        assert d.new_intensity == "easy"
        assert d.new_description == "Mobilite epaule"
        assert d.new_title == "Mobilite"
        assert msg == "J'ai adapte ta seance."

    def test_lighten_action(self):
        data = {
            "adaptations": [
                {"session_id": 10, "action": "lighten", "rationale": "Surcharge"}
            ],
            "message": "Allege.",
        }
        decisions, msg = _parse_adaptation_response(data)
        assert len(decisions) == 1
        assert decisions[0].mutation_type == "lighten_day"
        assert decisions[0].target_session_id == 10

    def test_mixed_actions(self):
        data = {
            "adaptations": [
                {"session_id": 1, "action": "keep", "rationale": "ok"},
                {"session_id": 2, "action": "replace", "new_sport_type": "strength",
                 "rationale": "adapt"},
                {"session_id": 3, "action": "lighten", "rationale": "trop"},
            ],
            "message": "Ajuste.",
        }
        decisions, msg = _parse_adaptation_response(data)
        assert len(decisions) == 2
        assert decisions[0].mutation_type == "replace_session"
        assert decisions[0].target_session_id == 2
        assert decisions[1].mutation_type == "lighten_day"
        assert decisions[1].target_session_id == 3

    def test_unknown_action_is_skipped(self):
        data = {
            "adaptations": [
                {"session_id": 1, "action": "cancel", "rationale": "nope"}
            ],
            "message": "?",
        }
        decisions, _ = _parse_adaptation_response(data)
        assert len(decisions) == 0
