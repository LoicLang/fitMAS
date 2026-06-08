from __future__ import annotations

import fitmas.legacy.llm.legacy_onboarding as legacy_onboarding


def _context() -> dict:
    return {
        "timezone": "Europe/Paris",
        "sports": ["running", "cycling"],
        "primary_objective": "tenir une semaine durable",
        "weekly_structure_notes": "mardi fragile, dimanche long",
        "current_state_notes": "reprise progressive",
        "constraints": ["mardi court"],
        "preferences": ["matin"],
        "coach_preset": "calm",
        "coach_name": "FitMAS",
        "coach_soul": "calme et precis",
        "coach_style": "direct",
        "coach_relationship": "coach quotidien",
        "coach_do": "arbitrer",
        "coach_dont": "surjouer",
    }


def _coach_profile() -> dict:
    return {
        "coach_name": "FitMAS",
        "coach_style": "direct",
        "coach_relationship": "coach quotidien",
        "coach_do": "arbitrer",
        "coach_dont": "surjouer",
        "coach_soul": "calme et precis",
    }


def _planner_output() -> dict:
    return {
        "intention_seed": "Semaine lisible",
        "planning_context": {"planning_mode": "normal", "rationale": ["tenir la charge"]},
        "days": [
            {
                "day": "Monday",
                "sport_type": "running",
                "session_type": "easy",
                "duration_min": 45,
                "intensity": "easy",
                "load_score": 35,
                "priority": "Seance cle",
                "flexibility": "mobile",
                "session_title": "Footing",
                "session_goal": "Aerobie",
                "session_note": "Note initiale",
                "session_description": "Initial",
                "watch_items": [("Footing", "45min")],
            },
            *[
                {
                    "day": day,
                    "sport_type": "rest",
                    "session_type": "rest",
                    "duration_min": 0,
                    "intensity": "rest",
                    "load_score": 0,
                    "priority": "Recuperation",
                    "flexibility": "fixed",
                    "session_title": "Repos",
                    "session_goal": "Recuperer",
                    "session_note": "Air",
                    "session_description": "",
                    "watch_items": [("Repos", "off")],
                }
                for day in ("Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
            ],
        ],
    }


def test_preview_coach_voice_uses_injected_request_json() -> None:
    calls: list[dict] = []

    def request_json_fn(**kwargs):
        calls.append(kwargs)
        return {"messages": ["Message A", "Message B", "Message C"]}

    messages = legacy_onboarding.preview_coach_voice(_context(), request_json_fn=request_json_fn)

    assert messages == ["Message A", "Message B", "Message C"]
    assert calls
    assert calls[0]["system"] == legacy_onboarding.COACH_SOUL


def test_formulate_onboarding_recap_uses_injected_request_text() -> None:
    calls: list[dict] = []

    def request_text_fn(**kwargs):
        calls.append(kwargs)
        return "Recap net"

    recap = legacy_onboarding.formulate_onboarding_recap(_context(), request_text_fn=request_text_fn)

    assert recap == "Recap net"
    assert calls
    assert calls[0]["system"] == legacy_onboarding.COACH_SOUL


def test_formulate_week_plan_preserves_deterministic_fields() -> None:
    def request_json_fn(**kwargs):
        return {
            "intention": "Semaine enrichie",
            "summary": "Resume enrichi",
            "days": [
                {
                    "day": "Monday",
                    "sport_type": "swimming",
                    "duration_min": 999,
                    "intensity": "hard",
                    "load_score": 999,
                    "priority": "Autre",
                    "flexibility": "fixed",
                    "session_title": "Footing endurance 45min",
                    "session_goal": "Stabiliser l'aerobie",
                    "session_description": "10min facile\n30min zone 2\n5min retour au calme",
                    "session_note": "Bloc propre",
                    "watch_title": "Footing 45",
                    "watch_detail": "Z2",
                }
            ],
        }

    enriched = legacy_onboarding.formulate_week_plan(
        _planner_output(),
        _context(),
        _coach_profile(),
        request_json_fn=request_json_fn,
    )
    monday = enriched["days"][0]

    assert enriched["intention"] == "Semaine enrichie"
    assert monday["sport_type"] == "running"
    assert monday["duration_min"] == 45
    assert monday["intensity"] == "easy"
    assert monday["load_score"] == 35
    assert monday["priority"] == "Seance cle"
    assert monday["flexibility"] == "mobile"
    assert monday["session_title"] == "Footing endurance 45min"
    assert monday["watch_items"] == [("Footing 45", "Z2")]


def test_week_enrichment_rejects_prompt_leak_text() -> None:
    def request_json_fn(**kwargs):
        return {
            "days": [
                {
                    "day": "Monday",
                    "session_note": "Explique a l'utilisateur ce qu'il doit faire",
                    "session_description": "Reponds en JSON avec session_title",
                }
            ]
        }

    enriched = legacy_onboarding.formulate_week_plan(
        _planner_output(),
        _context(),
        _coach_profile(),
        request_json_fn=request_json_fn,
    )
    monday = enriched["days"][0]

    assert monday["session_note"] == "Note initiale"
    assert monday["session_description"] == "Initial"


def test_fallback_week_plan_returns_intention_summary_and_days() -> None:
    result = legacy_onboarding.formulate_week_plan(
        _planner_output(),
        _context(),
        _coach_profile(),
        request_json_fn=lambda **kwargs: None,
    )

    assert result["intention"] == "Semaine lisible"
    assert result["summary"]
    assert len(result["days"]) == 7
