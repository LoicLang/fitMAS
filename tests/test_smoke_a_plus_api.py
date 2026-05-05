from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_a_plus_api",
        ROOT / "scripts" / "smoke_a_plus_api.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_guarded_no_commit_fails_when_a_risky_scenario_writes_an_event():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="move_hard_close",
        prompt="deplace la seance dure mercredi",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 1, "command_type": "move_session"},),
        pending=(),
        sessions=(),
        latest_turn={"response_mode": "mutation_applied", "assistant_message": "C'est deplace."},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "wrote 1 plan mutation event" in result.reasons


def test_guarded_no_commit_passes_when_risky_scenario_becomes_pending_plan_patch():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="replace_key_running_swim_easy",
        prompt="remplace la seance cle par natation",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 3, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_patch_confirmation",
            "pending_confirmation": True,
            "assistant_message": "Je te demande confirmation avant de toucher la seance cle.",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []


def test_guarded_no_commit_fails_when_pending_reply_claims_action_done():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="swap_key_and_recovery",
        prompt="echange fractionne et recuperation",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 5, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_patch_confirmation",
            "pending_confirmation": True,
            "assistant_message": "Echange fait. Tu confirmes pour garder ca ?",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "assistant claimed a mutation without committed event" in result.reasons


def test_no_plan_write_fails_on_pending_confirmation_too():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="memory_preference",
        prompt="je prefere courir le matin",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 4, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={"response_mode": "plan_patch_confirmation", "assistant_message": "Tu confirmes ?"},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "created 1 pending confirmation" in result.reasons


def test_coherent_commit_or_pending_fails_on_claim_without_event_or_pending():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="move_easy_to_free",
        prompt="deplace la seance facile",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={"response_mode": "reply", "assistant_message": "C'est deplace vendredi."},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "assistant claimed a mutation without event or pending confirmation" in result.reasons


def test_coherent_commit_or_pending_fails_on_backend_claim_guard_phrasing():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="move_easy_to_free",
        prompt="deplace la seance facile",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "reply",
            "assistant_message": "J'ai inverse la sortie longue et le fractionne.",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "assistant claimed a mutation without event or pending confirmation" in result.reasons


def test_reply_placeholders_are_reported_as_warnings_not_artifact_failures():
    smoke = _load_smoke_module()
    scenario = smoke.SmokeScenario(
        name="replace_key_running_swim_easy",
        prompt="remplace la seance cle",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 3, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_patch_confirmation",
            "pending_confirmation": True,
            "assistant_message": "On peut le mettre [jour] a la place de [seance X].",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []
    assert "assistant reply contains bracket placeholder" in result.warnings


def test_generated_week_response_fails_without_scheduled_sessions():
    smoke = _load_smoke_module()
    response = {
        "week_plan": {
            "summary": "Semaine test",
            "days": [_active_day("monday"), *_rest_days("tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")],
        }
    }
    snapshot = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)

    result = smoke.evaluate_generated_week_response("onboard", response, snapshot)

    assert not result.ok
    assert "created no scheduled sessions" in result.reasons


def test_generated_week_response_passes_with_active_week_and_sessions():
    smoke = _load_smoke_module()
    response = {
        "summary": "Semaine test",
        "days": [_active_day("monday"), *_rest_days("tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")],
    }
    snapshot = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(
            {
                "id": 1,
                "scheduled_date": "2026-05-04 00:00:00",
                "sport_type": "running",
                "session_type": "easy",
                "intensity": "easy",
                "duration_min": 40,
            },
        ),
        latest_turn=None,
    )

    result = smoke.evaluate_generated_week_response("regenerate", response, snapshot)

    assert result.ok
    assert result.reasons == []


def _active_day(day: str) -> dict:
    return {
        "day": day,
        "sport_type": "running",
        "session_type": "easy",
        "session_title": "Footing",
        "session_description": "40min easy",
        "duration_min": 40,
        "intensity": "easy",
    }


def _rest_days(*days: str) -> list[dict]:
    return [
        {
            "day": day,
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos",
            "session_description": "",
            "duration_min": None,
            "intensity": "easy",
        }
        for day in days
    ]
