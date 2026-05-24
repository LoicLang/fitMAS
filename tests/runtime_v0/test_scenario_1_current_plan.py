import json

from fitmas.runtime_v0.audit import load_turn
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_current_plan_lists_current_window_without_old_plan(tmp_path):
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

    result = handle_event(scenario.input_event, deps, turn_id="turn-current-plan")
    turn = load_turn(db_path, "turn-current-plan")
    proposal = json.loads(turn["proposal_json"])

    assert result.runtime_result.proposal_type == scenario.expected_proposal_type
    assert result.runtime_result.policy_action == scenario.expected_policy_action
    assert proposal["tool_trace"] == [{"name": "get_current_plan", "ok": True}]
    for expected in scenario.expected_reply_must_include:
        assert expected in result.reply
    for forbidden in scenario.expected_reply_must_not_contain:
        assert forbidden not in result.reply
    assert compare_persisted_turn(db_path, "turn-current-plan", scenario).success is True
