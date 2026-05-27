from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_matrix_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_coach_provider_matrix",
        ROOT / "scripts" / "smoke_coach_provider_matrix.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_matrix_defaults_cover_four_requested_profiles_and_human_scenarios():
    matrix = _load_matrix_module()

    assert matrix.DEFAULT_PROFILES == ("deepseek", "mistral", "gemini", "grok")
    assert matrix.DEFAULT_PROFILE_MODELS["gemini"] == "gemini-3.5-flash"
    assert matrix.DEFAULT_PROFILE_REASONING_EFFORTS["mistral"] == "high"
    assert matrix.DEFAULT_PROFILE_REASONING_EFFORTS["gemini"] == "medium"
    assert matrix.DEFAULT_PROFILE_REASONING_EFFORTS["grok"] == "low"
    assert {
        "human_missed_yesterday_short",
        "human_done_finally",
        "ambiguous_this_to_friday",
        "swim_unavailable_two_weeks_human",
        "fatigue_keep_light",
        "pending_ok_accept",
        "ok_without_pending",
        "pending_modify_saturday",
        "add_hard_tomorrow_loaded",
    } <= set(matrix.DEFAULT_HUMAN_SCENARIOS)


def test_matrix_builds_smoke_command_with_profile_output_and_scenarios(tmp_path):
    matrix = _load_matrix_module()

    command = matrix.build_smoke_command(
        profile="gemini",
        suite="human",
        scenarios=("ok_without_pending", "fatigue_keep_light"),
        output_dir=tmp_path / "gemini",
        timeout=240.0,
        port=8123,
    )

    assert command[:2] == [str(ROOT / "scripts" / "smoke-a-plus-api"), "--skip-generated-week"]
    assert "--scenario" in command
    assert "ok_without_pending" in command
    assert "fatigue_keep_light" in command
    assert str(tmp_path / "gemini" / "fallback_census.json") in command
    assert str(tmp_path / "gemini" / "smoke.db") in command
    assert "--keep-db" in command
    assert "8123" in command


def test_matrix_builds_existing_suite_commands(tmp_path):
    matrix = _load_matrix_module()

    daily = matrix.build_smoke_command(
        profile="deepseek",
        suite="daily",
        scenarios=(),
        output_dir=tmp_path / "deepseek" / "daily",
        timeout=300.0,
        port=8124,
    )
    extended = matrix.build_smoke_command(
        profile="deepseek",
        suite="extended",
        scenarios=(),
        output_dir=tmp_path / "deepseek" / "extended",
        timeout=300.0,
        port=8125,
    )

    assert "--daily" in daily
    assert "--extended" not in daily
    assert "--scenario" not in daily
    assert "--extended" in extended
    assert "--daily" not in extended


def test_matrix_extracts_assistant_replies_from_smoke_stdout():
    matrix = _load_matrix_module()

    scenarios = matrix.extract_scenario_outputs(
        "\n".join(
            [
                "SCENARIO ok_without_pending",
                "prompt: ok",
                "assistant: Impeccable, on en reste la.",
                "OK",
                "SCENARIO fatigue_keep_light",
                "prompt: je suis rince",
                "turn#1: je suis rince",
                "assistant: Je te propose leger.",
                "FAIL",
                "- canonical planning provider did not handle supported planning turn",
            ]
        )
    )

    assert scenarios["ok_without_pending"]["assistant_messages"] == ["Impeccable, on en reste la."]
    assert scenarios["ok_without_pending"]["status"] == "OK"
    assert scenarios["fatigue_keep_light"]["status"] == "FAIL"
    assert scenarios["fatigue_keep_light"]["reasons"] == [
        "canonical planning provider did not handle supported planning turn"
    ]
    assert scenarios["ok_without_pending"]["prompt"] == "ok"


def test_matrix_preserves_multiline_assistant_replies():
    matrix = _load_matrix_module()

    scenarios = matrix.extract_scenario_outputs(
        "\n".join(
            [
                "SCENARIO lookup_current_plan",
                "prompt: Redonne-moi le plan actuel, jour par jour.",
                "assistant: Voici le plan :",
                "",
                "Mercredi : Fractionne seuil.",
                "Jeudi : Sortie longue.",
                "artifacts: events=+0 pending=+0",
                "OK",
            ]
        )
    )

    assert scenarios["lookup_current_plan"]["assistant_messages"] == [
        "Voici le plan :\n\nMercredi : Fractionne seuil.\nJeudi : Sortie longue."
    ]
    assert scenarios["lookup_current_plan"]["artifacts"]["events_delta"] == 0
    assert scenarios["lookup_current_plan"]["artifacts"]["pending_delta"] == 0


def test_matrix_extracts_followups_and_artifacts():
    matrix = _load_matrix_module()

    scenarios = matrix.extract_scenario_outputs(
        "\n".join(
            [
                "SCENARIO pending_ok_accept",
                "prompt: Deplace la recup lundi",
                "turn#1: Deplace la recup lundi",
                "assistant: Tu confirmes ?",
                "turn#2: ok",
                "assistant: C'est fait.",
                "artifacts: events=+1 pending=+0 mode=pending_accepted mutation_applied=True session_changes=1",
                "OK",
            ]
        )
    )

    scenario = scenarios["pending_ok_accept"]
    assert scenario["prompt"] == "Deplace la recup lundi"
    assert scenario["turns"] == ["Deplace la recup lundi", "ok"]
    assert scenario["assistant_messages"] == ["Tu confirmes ?", "C'est fait."]
    assert scenario["artifacts"] == {
        "events_delta": 1,
        "pending_delta": 0,
        "response_mode": "pending_accepted",
        "mutation_applied": True,
        "session_changes": 1,
    }


def test_matrix_review_only_keeps_model_run_success_for_scenario_failures():
    matrix = _load_matrix_module()
    scenarios = {
        "fatigue_keep_light": {
            "status": "FAIL",
            "reasons": ["canonical planning provider did not handle supported planning turn"],
        }
    }

    assert matrix.status_for_completed_run(1, scenarios, review_only=True) == "reviewed"
    assert matrix.status_for_completed_run(1, scenarios, review_only=False) == "failed"


def test_matrix_review_only_still_fails_http_or_llm_errors():
    matrix = _load_matrix_module()
    scenarios = {
        "fatigue_keep_light": {
            "status": "FAIL",
            "reasons": ["HTTP/LLM error: timeout"],
        }
    }

    assert matrix.status_for_completed_run(1, scenarios, review_only=True) == "failed"


def test_matrix_review_only_still_fails_runtime_llm_unavailable():
    matrix = _load_matrix_module()
    scenarios = {
        "pending_modify_saturday": {
            "status": "FAIL",
            "reasons": [],
            "artifacts": {"response_mode": "llm_unavailable"},
        }
    }

    assert matrix.status_for_completed_run(1, scenarios, review_only=True) == "failed"


def test_matrix_accepts_grok_api_key_alias():
    matrix = _load_matrix_module()

    with patch.dict(os.environ, {"GROK_API_KEY": "sk-grok-test"}, clear=True):
        assert matrix._missing_env_for_profile("grok") is None
