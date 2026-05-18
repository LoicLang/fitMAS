from __future__ import annotations

import builtins
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


def test_canonical_planning_fails_on_duplicate_active_pending(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation puis confirme",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(
            {"id": 1, "status": "pending", "mutation_type": "plan_patch"},
            {"id": 2, "status": "pending", "mutation_type": "plan_patch"},
        ),
        sessions=(),
        latest_turn={"response_mode": "plan_patch_confirmation", "assistant_message": "Tu confirmes ?"},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "duplicate_pending" in result.reasons


def test_canonical_planning_confirm_without_pending_cannot_write(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="confirm_without_pending",
        prompt="oui je confirme",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 1, "command_type": "move_session"},),
        pending=(),
        sessions=(),
        latest_turn={"response_mode": "mutation_applied", "assistant_message": "C'est fait."},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "confirm_without_pending wrote planning artifact" in result.reasons


def test_canonical_planning_followup_path_allows_one_pending_row(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 7, "command_type": "apply_plan_patch"},),
        pending=({"id": 3, "status": "accepted", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "pending_accepted",
            "mutation_applied": True,
            "assistant_message": "C'est applique.",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"handled"},'
                    '"legacy_decide":{"legacy_skipped":true}}'
                ),
            },
            {
                "id": 2,
                "context_json": '{"canonical_pending_provider":{"result":"handled"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []


def test_default_planning_provider_requires_canonical_trace_for_supported_turn(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 7, "command_type": "move_session"},),
        pending=({"id": 3, "status": "accepted", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "pending_accepted",
            "mutation_applied": True,
            "assistant_message": "C'est applique.",
        },
        turns=(
            {
                "id": 1,
                "context_json": '{"legacy_decide":{"legacy_skipped":false}}',
            },
            {
                "id": 2,
                "context_json": '{"canonical_pending_provider":{"result":"handled"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons


def test_default_planning_provider_requires_canonical_trace_for_swap_by_day(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="swap_by_day",
        prompt="echange mercredi et jeudi",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 3, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_pending_confirmation",
            "pending_confirmation": True,
            "assistant_message": "Tu confirmes ?",
        },
        turns=(
            {"id": 1, "context_json": '{"legacy_decide":{"legacy_skipped":false}}'},
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons


def test_default_planning_provider_requires_canonical_trace_for_move_hard_close(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="move_hard_close",
        prompt="deplace la sortie longue de jeudi a mercredi",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 3, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_pending_confirmation",
            "pending_confirmation": True,
            "assistant_message": "Tu confirmes ?",
        },
        turns=(
            {
                "id": 1,
                "context_json": '{"canonical_planning_provider":{"result":"fallback_legacy"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons


def test_smoke_fails_unclassified_active_legacy_fallback(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="memory_preference",
        prompt="je prefere courir le matin",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "no_change_composed",
            "mutation_applied": False,
            "assistant_message": "C'est note.",
        },
        turns=(
            {"id": 1, "context_json": '{"legacy_decide":{"legacy_skipped":false}}'},
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "legacy fallback used without fallback census" in result.reasons


def test_default_planning_provider_accepts_canonical_planning_and_pending_traces(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 7, "command_type": "move_session"},),
        pending=({"id": 3, "status": "accepted", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "pending_accepted",
            "mutation_applied": True,
            "assistant_message": "C'est applique.",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"handled"},'
                    '"legacy_decide":{"legacy_skipped":true}}'
                ),
            },
            {
                "id": 2,
                "context_json": '{"canonical_pending_provider":{"result":"handled"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []


def test_default_planning_provider_rejects_planning_runtime_mode_without_canonical_provider_trace(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 7, "command_type": "move_session"},),
        pending=({"id": 3, "status": "accepted", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "pending_accepted",
            "mutation_applied": True,
            "assistant_message": "C'est applique.",
        },
        turns=(
            {
                "id": 1,
                "response_mode": "planning_runtime_pending_confirmation",
                "context_json": '{"legacy_decide":{"legacy_skipped":true}}',
            },
            {
                "id": 2,
                "context_json": '{"canonical_pending_provider":{"result":"handled"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons


def test_smoke_fails_closed_when_fallback_census_import_fails(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    real_import = builtins.__import__

    def broken_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "fitmas.decision.fallback_census":
            raise ImportError("fallback census unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    scenario = smoke.SmokeScenario(
        name="memory_preference",
        prompt="je prefere courir le matin",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "no_change_composed",
            "mutation_applied": False,
            "assistant_message": "C'est note.",
        },
        turns=(
            {"id": 1, "context_json": '{"legacy_decide":{"legacy_skipped":false}}'},
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "fallback_census_import_failed" in result.reasons


def test_smoke_fails_closed_when_fallback_census_runtime_fails(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    if str(smoke.BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(smoke.BACKEND_SRC))
    from fitmas.decision import fallback_census

    def broken_check(_context):
        raise RuntimeError("census broken")

    monkeypatch.setattr(fallback_census, "unclassified_legacy_fallback_reasons", broken_check)
    scenario = smoke.SmokeScenario(
        name="memory_preference",
        prompt="je prefere courir le matin",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "no_change_composed",
            "mutation_applied": False,
            "assistant_message": "C'est note.",
        },
        turns=(
            {"id": 1, "context_json": '{"legacy_decide":{"legacy_skipped":false}}'},
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "fallback_census_runtime_failed" in result.reasons


def test_canonical_planning_fails_on_candidate_backend_jargon(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="swim_unavailable_two_weeks",
        prompt="je ne peux pas nager deux semaines",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 1, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_pending_confirmation",
            "assistant_message": "Je te propose: Candidate backend, pas une reponse finale. Tu confirmes ?",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "assistant reply leaks internal jargon" in result.reasons


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


def test_daily_scenarios_are_opt_in_and_include_multi_turn_cases():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(None, include_daily=True)
    names = {scenario.name for scenario in selected}

    assert "body_metric_reassurance_thread" in names
    assert "execution_temporal_correction_thread" in names
    assert "move_easy_then_confirm" in names
    assert "move_hard_close" not in names
    assert any(scenario.followups for scenario in selected)


def test_named_selection_can_pick_daily_scenario_without_daily_flag():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(["body_metric_reassurance_thread"], include_daily=False)

    assert [scenario.name for scenario in selected] == ["body_metric_reassurance_thread"]


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
