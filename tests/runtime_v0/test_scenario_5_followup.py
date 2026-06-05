import json

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import compare_persisted_turn
from scripts.v0_eval.scenarios import scenario_by_name, seed_db


def test_followup_planning_preserves_intent_then_moves_recovery(tmp_path):
    scenario = scenario_by_name("followup_planning_turn1")
    followup = scenario.followup
    db_path = tmp_path / "fitmas_v0.db"
    seed_db(db_path, scenario.initial_db_state)
    deps_turn1 = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall("resolve_date_reference", {"weekday": "friday", "direction": "future"}),)),
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "ask_clarification",
                            {
                                "question": "Quelle séance veux-tu déplacer ?",
                                "unresolved_intent": {
                                    "type": "move_session",
                                    "target_date": "2026-05-29",
                                    "missing": ["source_ref"],
                                },
                            },
                        ),
                    )
                )
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Quelle séance veux-tu déplacer ?")]),
    )

    first = handle_event(scenario.input_event, deps_turn1, turn_id="turn-followup-1")

    with connect(db_path) as connection:
        state = connection.execute("select last_unresolved_intent_json from v0_conversation_state").fetchone()
    assert first.runtime_result.proposal_type == "ask_clarification"
    assert json.loads(state["last_unresolved_intent_json"]) == {
        "type": "move_session",
        "target_date": "2026-05-29",
        "missing": ["source_ref"],
    }
    assert compare_persisted_turn(db_path, "turn-followup-1", scenario).success is True
    assert followup is not None

    deps_turn2 = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_plan_patch",
                            {
                                "operations": [
                                    {
                                        "kind": "move",
                                        "source_session_id": 60,
                                        "target_date": "2026-05-29",
                                    }
                                ],
                                "rationale": "déplacer la séance de récup à vendredi",
                            },
                        ),
                    )
                )
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Déplacé à vendredi.")]),
    )

    second = handle_event(followup.input_event, deps_turn2, turn_id="turn-followup-2")

    with connect(db_path) as connection:
        session = connection.execute("select date from v0_scheduled_sessions where id = 60").fetchone()
        event = connection.execute(
            "select command_type, target_id, status from v0_command_events where command_type = 'ApplyPlanPatchCommand'"
        ).fetchone()
    assert session["date"] == "2026-05-29"
    assert (event["command_type"], event["target_id"], event["status"]) == (
        "ApplyPlanPatchCommand",
        "60",
        "applied",
    )
    assert second.runtime_result.proposal_type == followup.expected_proposal_type
    assert second.runtime_result.policy_action == followup.expected_policy_action
    assert "VMA" not in second.reply
    assert compare_persisted_turn(db_path, "turn-followup-2", followup).success is True
