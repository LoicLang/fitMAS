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


def test_default_planning_provider_requires_canonical_trace_for_add_hard_dense(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="add_hard_dense",
        prompt="ajoute une seance dure mercredi",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_block",
            "assistant_message": "Je bloque l'ajout.",
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


def test_default_planning_provider_requires_canonical_trace_for_trip_constraint(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="trip_constraint",
        prompt="Je voyage de mercredi a vendredi, adapte si besoin",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_block",
            "assistant_message": "Je bloque la recomposition large.",
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


def test_trip_constraint_accepts_canonical_pending_confirmation(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="trip_constraint",
        prompt="Je voyage de mercredi a vendredi, adapte si besoin",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 9, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "planning_runtime_pending_confirmation",
            "pending_confirmation": True,
            "pending_confirmation_id": 9,
            "assistant_message": "Je peux deplacer les seances touchees apres ton retour. Tu confirmes ?",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"handled"},'
                    '"legacy_decide":{"legacy_skipped":true}}'
                ),
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []


def test_trip_memory_only_does_not_require_canonical_planning_trace(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="trip_memory_only",
        prompt="Je voyage de mercredi a vendredi",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "no_change_composed",
            "assistant_message": "Je note la contrainte.",
        },
        turns=(
            {
                "id": 1,
                "context_json": '{"canonical_planning_provider":{"result":"fallback_legacy"}}',
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []


def test_default_planning_provider_requires_canonical_trace_for_replace_swim_with_bike(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="replace_swim_with_bike",
        prompt="remplace la natation dimanche par un velo facile",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "legacy_decision_contract_disabled",
            "assistant_message": "Ancienne forme de decision.",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"fallback_legacy"},'
                    '"fallback_census":[{"owner":"planning"}]}'
                ),
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons


def test_default_planning_provider_requires_canonical_trace_for_swim_unavailable(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
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


def test_fallback_census_report_lists_legacy_and_candidate_turns(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="ambiguous_move",
        prompt="mets la course plus tard",
        expectation="no_plan_write",
    )
    result = smoke.ScenarioCheckResult(ok=False, reasons=["created pending"], warnings=[])
    snapshot = smoke.DbSnapshot(
        events=(),
        pending=({"id": 1, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={"response_mode": "plan_adaptation_pending_confirmation"},
        turns=(
            {
                "id": 1,
                "response_mode": "plan_adaptation_pending_confirmation",
                "user_message": "mets la course plus tard",
                "assistant_message": "Tu confirmes ?",
                "context_json": (
                    '{"fallback_census":[{"owner":"planning",'
                    '"source":"canonical_planning_provider"}],'
                    '"adaptation_candidate_flow":{"selected_candidate_id":"c1"},'
                    '"canonical_planning_provider":{"result":"fallback_legacy"},'
                    '"legacy_decide":{"legacy_skipped":false},'
                    '"canonical_understanding":{"intent":"plan_change",'
                    '"confidence":0.3,"requested_change":{},'
                    '"extracted_signals":[{}]}}'
                ),
            },
        ),
    )

    report = smoke._fallback_census_for_scenario(scenario, result, snapshot)

    assert report["scenario"] == "ambiguous_move"
    assert report["fallback_turn_count"] == 1
    assert report["owner_counts"] == {"planning": 1}
    assert report["source_counts"] == {"canonical_planning_provider": 1}
    assert report["turns"][0]["response_mode"] == "plan_adaptation_pending_confirmation"
    assert report["turns"][0]["adaptation_candidate_flow"] == {"selected_candidate_id": "c1"}
    assert report["turns"][0]["canonical_understanding"] == {
        "intent": "plan_change",
        "confidence": 0.3,
        "requested_change": {},
        "requested_change_count": 1,
        "signal_count": 1,
    }


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
        if name == "fitmas.legacy.decision.fallback_census":
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
    from fitmas.legacy.decision import fallback_census

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


def test_daily_smoke_contains_human_realistic_regression_cases():
    smoke = _load_smoke_module()

    daily_names = {scenario.name for scenario in smoke.DAILY_SCENARIOS}

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
    } <= daily_names


def test_new_human_planning_cases_require_canonical_planning_trace():
    smoke = _load_smoke_module()

    assert {
        "swim_unavailable_two_weeks_human",
        "fatigue_keep_light",
        "pending_ok_accept",
        "pending_modify_saturday",
        "add_hard_tomorrow_loaded",
    } <= smoke._CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS


def test_new_human_cases_are_selectable_in_order():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(
        [
            "human_missed_yesterday_short",
            "ambiguous_this_to_friday",
            "ok_without_pending",
        ]
    )

    assert [scenario.name for scenario in selected] == [
        "human_missed_yesterday_short",
        "ambiguous_this_to_friday",
        "ok_without_pending",
    ]


def test_daily_scenarios_are_opt_in_and_include_multi_turn_cases():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(None, include_daily=True)
    names = {scenario.name for scenario in selected}

    assert "body_metric_reassurance_thread" in names
    assert "execution_temporal_correction_thread" in names
    assert "move_easy_then_confirm" in names
    assert "move_hard_close" not in names
    assert any(scenario.followups for scenario in selected)


def test_extended_scenarios_are_opt_in_and_cover_probe_groups():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(None, include_extended=True)
    names = {scenario.name for scenario in selected}

    assert "pending_reject_move" in names
    assert "execution_wrong_sport_correction" in names
    assert "health_adapt_knee" in names
    assert "one_day_unavailable_affected" in names
    assert "why_this_workout" in names
    assert "elliptical_friday_morning" in names
    assert "memory_goal_update" in names
    assert "move_hard_close" not in names
    assert "close_turn_ack" not in names


def test_named_selection_can_pick_extended_scenario_without_extended_flag():
    smoke = _load_smoke_module()

    selected = smoke._selected_scenarios(["pending_reject_move"])

    assert [scenario.name for scenario in selected] == ["pending_reject_move"]


def test_parse_args_rejects_daily_and_extended_together():
    smoke = _load_smoke_module()

    try:
        smoke.parse_args(["--daily", "--extended"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parse_args to reject --daily with --extended")


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
