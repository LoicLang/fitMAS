"""Tests for the adaptation module triggers and response parsing."""

from fitmas.adaptation import (
    _HIGH_URGENCY_KEYWORDS,
    _build_conservative_health_fallback,
    _model_for_trigger,
    _parse_adaptation_response,
    _should_force_conservative_health_fallback,
    AdaptationTrigger,
)


class TestHighUrgencyKeywords:
    def test_douleur_is_high(self):
        assert "douleur" in _HIGH_URGENCY_KEYWORDS

    def test_fatigue_is_high(self):
        assert "fatigue" in _HIGH_URGENCY_KEYWORDS

    def test_blessure_is_high(self):
        assert "blessure" in _HIGH_URGENCY_KEYWORDS


class TestModelSelection:
    def test_health_fact_uses_valid_sonnet_alias(self):
        assert _model_for_trigger("health_fact") == "claude-sonnet-4-6"

    def test_other_triggers_use_haiku(self):
        assert _model_for_trigger("post_activity") == "claude-haiku-4-5-20251001"


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
                {"session_id": 2, "action": "replace", "new_sport_type": "strength", "rationale": "adapt"},
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


class TestConservativeHealthFallback:
    def test_swimming_shoulder_signal_replaces_next_swim_session(self):
        trigger = AdaptationTrigger(
            trigger_type="health_fact",
            urgency="immediate",
            affected_session_ids=[5],
            context_data={
                "health_facts": [
                    {
                        "category": "health",
                        "key": "reported_health_shoulder_swimming",
                        "value": "gene a la zone shoulder quand il fait swimming. severite moderate.",
                    }
                ],
                "sessions": [
                    {
                        "id": 5,
                        "sport_type": "swimming",
                        "session_type": "endurance",
                        "title": "Natation endurance",
                        "duration_min": 45,
                    }
                ],
            },
        )

        decisions, message = _build_conservative_health_fallback(trigger)

        assert len(decisions) == 1
        assert decisions[0].mutation_type == "replace_session"
        assert decisions[0].target_session_id == 5
        assert decisions[0].new_session_type == "mobility"
        assert decisions[0].new_intensity == "easy"
        assert "coupe la natation" in message

    def test_swimming_shoulder_signal_forces_conservative_path(self):
        trigger = AdaptationTrigger(
            trigger_type="health_fact",
            urgency="immediate",
            affected_session_ids=[5],
            context_data={
                "health_facts": [
                    {
                        "category": "health",
                        "key": "reported_health_shoulder_swimming",
                        "value": "douleur a la zone shoulder quand il fait swimming. severite moderate.",
                    }
                ],
                "sessions": [],
            },
        )

        assert _should_force_conservative_health_fallback(trigger) is True
