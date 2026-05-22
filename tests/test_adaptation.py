"""Tests for the adaptation module triggers and response parsing."""

from types import SimpleNamespace

import fitmas.domain.planning.adaptation as adaptation

from fitmas.domain.planning.adaptation import (
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


class TestRunAdaptationFreeze:
    def test_run_adaptation_returns_suggestion_only_by_default(self, monkeypatch):
        trigger = AdaptationTrigger(
            trigger_type="post_activity",
            urgency="next_session",
            affected_session_ids=[7],
            context_data={
                "activity": {"sport": "running", "duration_min": 60, "tss": 40.0},
                "matched_session": {"id": 7, "sport_type": "running", "title": "Tempo"},
                "reasons": ["charge haute"],
                "tsb": -22.0,
                "sessions_48h": [],
            },
        )
        user = SimpleNamespace(id=1, timezone="Europe/Paris")

        monkeypatch.setattr(
            "fitmas.llm.gateway.request_json",
            lambda **kwargs: {
                "adaptations": [
                    {"session_id": 7, "action": "lighten", "rationale": "charge haute"}
                ],
                "message": "Je te proposerais d'alleger la suite.",
            },
        )
        called = {"apply": False}

        def _fail_apply(*args, **kwargs):
            called["apply"] = True
            raise AssertionError("mutations.apply should stay off by default")

        monkeypatch.setattr("fitmas.domain.planning.mutation_executor.apply", _fail_apply)

        result = adaptation.run_adaptation(object(), user=user, trigger=trigger)

        assert result is not None
        assert result.applied is False
        assert len(result.decisions) == 1
        assert called["apply"] is False

    def test_run_adaptation_stays_suggestion_only(self, monkeypatch):
        trigger = AdaptationTrigger(
            trigger_type="post_activity",
            urgency="next_session",
            affected_session_ids=[7],
            context_data={
                "activity": {"sport": "running", "duration_min": 60, "tss": 40.0},
                "matched_session": {"id": 7, "sport_type": "running", "title": "Tempo"},
                "reasons": ["charge haute"],
                "tsb": -22.0,
                "sessions_48h": [],
            },
        )
        user = SimpleNamespace(id=1, timezone="Europe/Paris")

        monkeypatch.setattr(
            "fitmas.llm.gateway.request_json",
            lambda **kwargs: {
                "adaptations": [
                    {"session_id": 7, "action": "lighten", "rationale": "charge haute"}
                ],
                "message": "Je te propose d'alleger la suite.",
            },
        )
        calls = {"apply": 0}

        def _record_apply(*args, **kwargs):
            calls["apply"] += 1
            raise AssertionError("adaptation.py must not apply mutations directly")

        monkeypatch.setattr("fitmas.domain.planning.mutation_executor.apply", _record_apply)

        result = adaptation.run_adaptation(object(), user=user, trigger=trigger)

        assert result is not None
        assert result.applied is False
        assert len(result.decisions) == 1
        assert calls["apply"] == 0

    def test_adaptation_module_does_not_import_plan_mutation_service(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / "backend/src/fitmas/domain/planning/adaptation.py").read_text()
        assert "plan_mutation_service" not in source

    def test_conversation_does_not_request_adaptation_auto_apply(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / "backend/src/fitmas/conversation_pipeline.py").read_text()
        assert "allow_apply=True" not in source

    def test_adaptation_api_no_longer_exposes_allow_apply(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / "backend/src/fitmas/domain/planning/adaptation.py").read_text()
        assert "allow_apply" not in source
