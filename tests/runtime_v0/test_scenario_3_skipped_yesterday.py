from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_skipped_yesterday_marks_right_session_skipped(tmp_path):
    scenario = scenario_by_name("skipped_yesterday")
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_execution_update",
                            {"session_id": 66, "status": "skipped", "evidence": "pas fait hier"},
                        ),
                    )
                )
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Noté pour hier.")]),
    )

    result = handle_event(scenario.input_event, deps, turn_id="turn-skipped")

    with connect(db_path) as connection:
        session = connection.execute("select status from v0_scheduled_sessions where id = 66").fetchone()
        event = connection.execute("select command_type, target_id, status from v0_command_events").fetchone()
    assert session["status"] == "skipped"
    assert (event["command_type"], event["target_id"], event["status"]) == (
        "SetSessionStatusCommand",
        "66",
        "applied",
    )
    assert result.runtime_result.proposal_type == scenario.expected_proposal_type
    assert result.runtime_result.policy_action == scenario.expected_policy_action
    for expected in scenario.expected_reply_must_include:
        assert expected in result.reply.lower()
    assert compare_persisted_turn(db_path, "turn-skipped", scenario).success is True
