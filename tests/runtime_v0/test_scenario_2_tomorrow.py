import json

from fitmas.runtime_v0.audit import load_turn
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_tomorrow_answers_only_tomorrow(tmp_path):
    scenario = scenario_by_name("tomorrow")
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall("get_plan_day", {"date": "2026-05-23"}),)),
                LLMResponse(text="23 Endurance facile."),
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="23 Endurance facile.")]),
    )

    result = handle_event(scenario.input_event, deps, turn_id="turn-tomorrow")
    proposal = json.loads(load_turn(db_path, "turn-tomorrow")["proposal_json"])

    assert result.runtime_result.proposal_type == scenario.expected_proposal_type
    assert result.runtime_result.policy_action == scenario.expected_policy_action
    assert proposal["tool_trace"] == [{"name": "get_plan_day", "ok": True}]
    for expected in scenario.expected_reply_must_include:
        assert expected in result.reply
    for forbidden in scenario.expected_reply_must_not_contain:
        assert forbidden not in result.reply.lower()
    assert compare_persisted_turn(db_path, "turn-tomorrow", scenario).success is True
