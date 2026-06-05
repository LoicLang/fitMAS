from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_execution_correction_targets_previous_event_and_session(tmp_path):
    scenario = scenario_by_name("execution_correction")
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_execution_correction",
                            {
                                "previous_event_id": 17,
                                "correct_session_id": 66,
                                "correct_status": "done",
                                "duration_min": 25,
                                "intensity_note": "easy",
                                "evidence": "fait finalement",
                            },
                        ),
                    )
                )
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Corrigé: 25 minutes.")]),
    )

    result = handle_event(scenario.input_event, deps, turn_id="turn-correction")

    with connect(db_path) as connection:
        session = connection.execute(
            "select status, duration_min from v0_scheduled_sessions where id = 66"
        ).fetchone()
        event = connection.execute(
            """
            select command_type, target_id, status
            from v0_command_events
            where command_type = 'CorrectSessionStatusCommand'
            """
        ).fetchone()
    assert session["status"] == "done"
    assert session["duration_min"] == 25
    assert (event["command_type"], event["target_id"], event["status"]) == (
        "CorrectSessionStatusCommand",
        "66",
        "applied",
    )
    assert result.runtime_result.proposal_type == scenario.expected_proposal_type
    assert result.runtime_result.policy_action == scenario.expected_policy_action
    assert "25" in result.reply
    assert compare_persisted_turn(db_path, "turn-correction", scenario).success is True
