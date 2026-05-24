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
