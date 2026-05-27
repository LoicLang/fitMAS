import json

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn, compare_run_to_oracle
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_oracle_compare_accepts_current_plan_run(tmp_path):
    scenario = scenario_by_name("current_plan")
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall("get_current_plan", {"days": 7}),)),
                LLMResponse(text="22 Footing recup, 24 VMA courte, 26 Endurance."),
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="22 Footing recup. 24 VMA courte. 26 Endurance.")]),
    )

    handle_event(scenario.input_event, deps, turn_id="turn-current-plan")

    verdict = compare_persisted_turn(db_path, "turn-current-plan", scenario)

    assert verdict.success is True
    assert verdict.required_read_tool_called is True
    assert verdict.wrong_write_count == 0
    assert verdict.old_plan_date_detected is False
    assert verdict.failures == ()


def test_oracle_compare_rejects_missing_required_read_tool():
    scenario = scenario_by_name("tomorrow")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "23 Endurance facile.",
            "tool_trace": [],
            "command_events": [],
            "guard_ok": True,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.required_read_tool_called is False
    assert "required_read_tool_missing" in verdict.failures


def test_oracle_compare_accepts_session_read_for_tomorrow_answer():
    scenario = scenario_by_name("tomorrow")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "23 Endurance facile.",
            "tool_trace": [{"name": "get_session", "ok": True}],
            "command_events": [],
            "guard_ok": True,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.required_read_tool_called is True
    assert "required_read_tool_missing" not in verdict.failures


def test_oracle_compare_allows_today_context_in_tomorrow_reply():
    scenario = scenario_by_name("tomorrow")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "Aujourd'hui je ne change rien. Demain 23: Endurance facile.",
            "tool_trace": [{"name": "get_plan_day", "ok": True}],
            "command_events": [],
            "guard_ok": True,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.reply_must_not_contain_ok is True
    assert "reply_contains_forbidden_text" not in verdict.failures


def test_oracle_compare_counts_wrong_writes_for_answer_only_scenario():
    scenario = scenario_by_name("current_plan")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "22 Footing recup. 24 VMA courte. 26 Endurance.",
            "tool_trace": [{"name": "get_current_plan", "ok": True}],
            "command_events": [
                {
                    "command_type": "SetSessionStatusCommand",
                    "target_type": "session",
                    "target_id": "60",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.wrong_write_count == 1
    assert "wrong_write" in verdict.failures


def test_oracle_compare_detects_old_plan_dates_in_reply():
    scenario = scenario_by_name("current_plan")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "7 mai Ancien run. 22 Footing recup. 24 VMA courte. 26 Endurance.",
            "tool_trace": [{"name": "get_current_plan", "ok": True}],
            "command_events": [],
            "guard_ok": True,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.old_plan_date_detected is True
    assert "old_plan_date_detected" in verdict.failures


def test_oracle_compare_detects_wrong_correction_target_event():
    scenario = scenario_by_name("execution_correction")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "execution_correction",
            "policy_action": "allow_commit",
            "reply": "Corrigé: 25 minutes.",
            "tool_trace": [],
            "command_events": [
                {
                    "command_type": "CorrectSessionStatusCommand",
                    "target_type": "session",
                    "target_id": "999",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {
                "type": "execution_correction",
                "execution_correction": {
                    "previous_event_id": 999,
                    "correct_session_id": 66,
                    "correct_status": "done",
                },
            },
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.wrong_correction_target is True
    assert "wrong_correction_target" in verdict.failures


def test_oracle_compare_does_not_count_missing_correction_as_wrong_target():
    scenario = scenario_by_name("execution_correction")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "execution_update",
            "policy_action": "ask_clarification",
            "reply": "Quelle séance ?",
            "tool_trace": [{"name": "propose_execution_update", "ok": True}],
            "command_events": [],
            "guard_ok": True,
            "proposal": {
                "type": "execution_update",
                "execution_update": {"session_id": 66, "status": "done"},
            },
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.wrong_correction_target is False
    assert "wrong_correction_target" not in verdict.failures


def test_oracle_compare_accepts_update_compiled_to_correction_command():
    scenario = scenario_by_name("execution_correction")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "execution_update",
            "policy_action": "allow_commit",
            "reply": "Corrigé: 25 minutes.",
            "tool_trace": [{"name": "get_recent_execution_events", "ok": True}],
            "command_events": [
                {
                    "command_type": "CorrectSessionStatusCommand",
                    "target_type": "session",
                    "target_id": "66",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {
                "type": "execution_update",
                "execution_update": {"session_id": 66, "status": "partial", "duration_min": 25},
            },
        },
        scenario,
    )

    assert verdict.proposal_type_ok is True
    assert verdict.wrong_correction_target is False
    assert verdict.success is True


def test_oracle_compare_detects_reply_claim_without_event():
    scenario = scenario_by_name("followup_planning_turn1")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "ask_clarification",
            "policy_action": "ask_clarification",
            "reply": "C'est fait, déplacé à vendredi.",
            "tool_trace": [],
            "command_events": [],
            "guard_ok": True,
            "proposal": {"type": "ask_clarification"},
        },
        scenario,
    )

    assert verdict.success is False
    assert verdict.reply_claim_without_event is True
    assert "reply_claim_without_event" in verdict.failures


def test_oracle_compare_accepts_any_reply_include_group():
    scenario = scenario_by_name("key_session_pending")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "create_pending",
            "reply": "Tu souhaites décaler la VMA à vendredi ? Validez-vous ce changement ?",
            "tool_trace": [{"name": "resolve_date_reference", "ok": True}, {"name": "get_session", "ok": True}],
            "command_events": [
                {
                    "command_type": "CreatePendingConfirmationCommand",
                    "target_type": "pending",
                    "target_id": "plan_patch",
                    "status": "applied",
                }
            ],
            "final_session_dates": {"61": "2026-05-23"},
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.reply_must_include_ok is True
    assert "reply_missing_expected_text" not in verdict.failures


def test_oracle_compare_accepts_followup_move_noun_form():
    scenario = scenario_by_name("followup_planning_turn1").followup
    assert scenario is not None

    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "allow_commit",
            "reply": "Déplacement de la séance de récup au vendredi 29 mai.",
            "tool_trace": [{"name": "propose_plan_patch", "ok": True}],
            "command_events": [
                {
                    "command_type": "ApplyPlanPatchCommand",
                    "target_type": "session",
                    "target_id": "60",
                    "status": "applied",
                }
            ],
            "final_session_dates": {"60": "2026-05-29"},
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.reply_must_include_ok is True
    assert "reply_missing_expected_text" not in verdict.failures


def test_oracle_compare_allows_confirmed_word_after_committed_lighten():
    scenario = scenario_by_name("explicit_lighten")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "allow_commit",
            "reply": "Séance de demain allégée et confirmée.",
            "tool_trace": [{"name": "get_session", "ok": True}],
            "command_events": [
                {
                    "command_type": "ApplyPlanPatchCommand",
                    "target_type": "session",
                    "target_id": "70",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.reply_must_not_contain_ok is True
    assert "reply_contains_forbidden_text" not in verdict.failures


def test_oracle_compare_accepts_lighten_noun_form():
    scenario = scenario_by_name("explicit_lighten")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "allow_commit",
            "reply": "Allègement validé: séance plus facile demain.",
            "tool_trace": [{"name": "get_session", "ok": True}],
            "command_events": [
                {
                    "command_type": "ApplyPlanPatchCommand",
                    "target_type": "session",
                    "target_id": "70",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.reply_must_include_ok is True
    assert verdict.reply_must_not_contain_ok is True


def test_oracle_compare_keeps_reply_wording_out_of_correctness_failures():
    scenario = scenario_by_name("explicit_lighten")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "allow_commit",
            "reply": "C'est pris en compte.",
            "tool_trace": [{"name": "get_session", "ok": True}],
            "command_events": [
                {
                    "command_type": "ApplyPlanPatchCommand",
                    "target_type": "session",
                    "target_id": "70",
                    "status": "applied",
                }
            ],
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.success is True
    assert verdict.failures == ()
    assert verdict.reply_quality_ok is False
    assert verdict.reply_quality_failures == ("reply_missing_expected_text",)


def test_oracle_compare_rejects_forbidden_pending_plan_apply():
    scenario = scenario_by_name("key_session_pending")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "plan_patch",
            "policy_action": "create_pending",
            "reply": "Je dois confirmer avant de faire ça: déplacer la VMA à vendredi.",
            "tool_trace": [{"name": "resolve_date_reference", "ok": True}, {"name": "get_session", "ok": True}],
            "command_events": [
                {
                    "command_type": "CreatePendingConfirmationCommand",
                    "target_type": "pending",
                    "target_id": "plan_patch",
                    "status": "applied",
                },
                {
                    "command_type": "ApplyPlanPatchCommand",
                    "target_type": "session",
                    "target_id": "61",
                    "status": "applied",
                },
            ],
            "final_session_dates": {"61": "2026-05-23"},
            "guard_ok": True,
            "proposal": {"type": "plan_patch"},
        },
        scenario,
    )

    assert verdict.forbidden_commands_absent is False
    assert "forbidden_command_present" in verdict.failures


def test_oracle_compare_allows_guard_repaired_reply_when_visible_contract_passes():
    scenario = scenario_by_name("current_plan")
    verdict = compare_run_to_oracle(
        {
            "proposal_type": "answer",
            "policy_action": "answer_only",
            "reply": "22 Footing recup. 24 VMA courte. 26 Endurance.",
            "tool_trace": [{"name": "get_current_plan", "ok": True}],
            "command_events": [],
            "guard_ok": False,
            "proposal": {"type": "answer"},
        },
        scenario,
    )

    assert verdict.guard_ok is False
    assert "guard_blocked" not in verdict.failures
    assert verdict.success is True


def test_oracle_compare_detects_wrong_final_session_date_for_followup(tmp_path):
    scenario = scenario_by_name("followup_planning_turn1")
    followup = scenario.followup
    assert followup is not None
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_conversation_state (user_id, last_unresolved_intent_json) values (?, ?)",
            (1, json.dumps({"type": "move_session", "target_date": "2026-05-23", "missing": ["source_ref"]})),
        )
        connection.commit()
    deps_turn2 = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_plan_patch",
                            {
                                "operations": [{"kind": "move", "source_session_id": 60, "target_date": "2026-05-23"}],
                                "rationale": "déplacer la séance de récup à vendredi",
                            },
                        ),
                    )
                )
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Déplacé à vendredi.")]),
    )
    handle_event(followup.input_event, deps_turn2, turn_id="turn-followup-2")

    verdict = compare_persisted_turn(db_path, "turn-followup-2", followup)

    assert verdict.success is False
    assert "final_session_date_mismatch" in verdict.failures
