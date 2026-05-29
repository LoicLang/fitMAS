from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from fitmas.runtime_v0.audit import load_turn
from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.proposals import proposal_to_dict
from scripts.v0_eval.scenarios import CommandSpec, ScenarioOracle


@dataclass(frozen=True)
class OracleVerdict:
    scenario: str
    success: bool
    reply_quality_ok: bool
    proposal_type_ok: bool
    policy_action_ok: bool
    expected_commands_ok: bool
    required_read_tool_called: bool
    wrong_write_count: int
    old_plan_date_detected: bool
    wrong_correction_target: bool
    final_session_dates_ok: bool
    forbidden_commands_absent: bool
    reply_claim_without_event: bool
    reply_must_include_ok: bool
    reply_must_not_contain_ok: bool
    guard_ok: bool
    failures: tuple[str, ...]
    reply_quality_failures: tuple[str, ...]


def compare_persisted_turn(db_path: Path, turn_id: str, oracle: ScenarioOracle) -> OracleVerdict:
    turn = load_turn(db_path, turn_id)
    if turn is None:
        raise LookupError(f"turn_not_found:{turn_id}")
    command_events = _load_command_events(db_path, turn_id)
    result = _turn_row_to_result(turn, command_events)
    result["final_session_dates"] = _load_session_dates(db_path, tuple(session_id for session_id, _ in oracle.expected_session_dates))
    return compare_run_to_oracle(result, oracle)


def compare_run_to_oracle(turn_result: Any, oracle: ScenarioOracle) -> OracleVerdict:
    run = _normalize_turn_result(turn_result)
    reply = str(run["reply"])
    reply_lower = reply.lower()
    command_events = tuple(run["command_events"])

    proposal_type_ok = _proposal_type_ok(run, command_events, oracle)
    policy_action_ok = run["policy_action"] == oracle.expected_policy_action
    expected_commands_ok = _expected_commands_ok(command_events, oracle.expected_commands)
    required_read_tool_called = _required_read_tool_called(run["tool_trace"], oracle)
    wrong_write_count = _wrong_write_count(command_events, oracle.expected_commands)
    old_plan_date_detected = _old_plan_date_detected(reply_lower, oracle)
    wrong_correction_target = _wrong_correction_target(run["proposal"], command_events, oracle)
    final_session_dates_ok = _final_session_dates_ok(run["final_session_dates"], oracle)
    forbidden_commands_absent = _forbidden_commands_absent(command_events, oracle)
    reply_claim_without_event = _reply_claim_without_event(reply_lower, command_events)
    reply_must_include_ok = all(
        expected.lower() in reply_lower for expected in oracle.expected_reply_must_include
    ) and all(
        any(expected.lower() in reply_lower for expected in expected_group)
        for expected_group in oracle.expected_reply_any_include
    )
    reply_must_not_contain_ok = all(
        forbidden.lower() not in reply_lower for forbidden in oracle.expected_reply_must_not_contain
    )
    guard_ok = bool(run["guard_ok"])
    reply_quality_failures = _reply_quality_failures(
        reply_must_include_ok=reply_must_include_ok,
        reply_must_not_contain_ok=reply_must_not_contain_ok,
    )

    failures = _failures(
        proposal_type_ok=proposal_type_ok,
        policy_action_ok=policy_action_ok,
        expected_commands_ok=expected_commands_ok,
        required_read_tool_called=required_read_tool_called,
        wrong_write_count=wrong_write_count,
        old_plan_date_detected=old_plan_date_detected,
        wrong_correction_target=wrong_correction_target,
        final_session_dates_ok=final_session_dates_ok,
        forbidden_commands_absent=forbidden_commands_absent,
        reply_claim_without_event=reply_claim_without_event,
        guard_ok=guard_ok,
    )
    return OracleVerdict(
        scenario=oracle.name,
        success=failures == (),
        reply_quality_ok=reply_quality_failures == (),
        proposal_type_ok=proposal_type_ok,
        policy_action_ok=policy_action_ok,
        expected_commands_ok=expected_commands_ok,
        required_read_tool_called=required_read_tool_called,
        wrong_write_count=wrong_write_count,
        old_plan_date_detected=old_plan_date_detected,
        wrong_correction_target=wrong_correction_target,
        final_session_dates_ok=final_session_dates_ok,
        forbidden_commands_absent=forbidden_commands_absent,
        reply_claim_without_event=reply_claim_without_event,
        reply_must_include_ok=reply_must_include_ok,
        reply_must_not_contain_ok=reply_must_not_contain_ok,
        guard_ok=guard_ok,
        failures=failures,
        reply_quality_failures=reply_quality_failures,
    )


def _load_command_events(db_path: Path, turn_id: str) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            select command_type, target_type, target_id, status
            from v0_command_events
            where turn_id = ?
            order by id
            """,
            (turn_id,),
        ).fetchall()
    return tuple(dict(row) for row in rows)

def _load_session_dates(db_path: Path, session_ids: tuple[str, ...]) -> dict[str, str]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    with connect(db_path) as connection:
        rows = connection.execute(f"select id, date from v0_scheduled_sessions where id in ({placeholders})", session_ids).fetchall()
    return {str(row["id"]): row["date"] for row in rows}


def _turn_row_to_result(turn: Any, command_events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    proposal = json.loads(turn["proposal_json"])
    result = json.loads(turn["result_json"])
    return {
        "proposal_type": result.get("proposal_type") or proposal.get("type"),
        "policy_action": result.get("policy_action"),
        "reply": turn["reply"],
        "tool_trace": proposal.get("tool_trace", []),
        "command_events": command_events,
        "final_session_dates": {},
        "guard_ok": bool(turn["guard_ok"]),
        "proposal": proposal,
    }


def _normalize_turn_result(turn_result: Any) -> dict[str, Any]:
    if isinstance(turn_result, dict):
        return {
            "proposal_type": turn_result.get("proposal_type"),
            "policy_action": turn_result.get("policy_action"),
            "reply": turn_result.get("reply", ""),
            "tool_trace": tuple(turn_result.get("tool_trace", ())),
            "command_events": tuple(turn_result.get("command_events", ())),
            "final_session_dates": dict(turn_result.get("final_session_dates", {})),
            "guard_ok": turn_result.get("guard_ok", True),
            "proposal": turn_result.get("proposal", {}),
        }
    if hasattr(turn_result, "runtime_result"):
        result = turn_result.runtime_result
        proposal = proposal_to_dict(turn_result.proposal)
        return {
            "proposal_type": result.proposal_type,
            "policy_action": result.policy_action,
            "reply": turn_result.reply,
            "tool_trace": tuple(proposal.get("tool_trace", ())),
            "command_events": tuple(
                {
                    "command_type": event.command_type,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "status": event.status,
                }
                for event in result.committed_events
            ),
            "final_session_dates": {},
            "guard_ok": turn_result.guard.ok,
            "proposal": proposal,
        }
    raise TypeError(f"unsupported_turn_result:{type(turn_result).__name__}")


def _expected_commands_ok(
    command_events: tuple[dict[str, Any], ...],
    expected_commands: tuple[CommandSpec, ...],
) -> bool:
    return all(_has_command(command_events, expected) for expected in expected_commands)


def _proposal_type_ok(run: dict[str, Any], command_events: tuple[dict[str, Any], ...], oracle: ScenarioOracle) -> bool:
    if run["proposal_type"] == oracle.expected_proposal_type:
        return True
    if oracle.name == "execution_correction" and run["proposal_type"] == "execution_update":
        return any(
            expected.command_type == "CorrectSessionStatusCommand" and _has_command(command_events, expected)
            for expected in oracle.expected_commands
        )
    return False


def _has_command(command_events: tuple[dict[str, Any], ...], expected: CommandSpec) -> bool:
    return any(_matches_command(event, expected) for event in command_events)


def _matches_command(event: dict[str, Any], expected: CommandSpec) -> bool:
    if event.get("command_type") != expected.command_type:
        return False
    if event.get("target_type") != expected.target_type:
        return False
    if expected.target_id is not None and str(event.get("target_id")) != str(expected.target_id):
        return False
    return event.get("status") == expected.expected_status


def _required_read_tool_called(tool_trace: tuple[dict[str, Any], ...], oracle: ScenarioOracle) -> bool:
    ok_tools = {item.get("name") for item in tool_trace if item.get("ok", True)}
    if oracle.name == "current_plan":
        return "get_current_plan" in ok_tools
    if oracle.name == "tomorrow":
        return bool({"get_plan_day", "get_current_plan", "get_session"} & ok_tools)
    return True


# Bookkeeping / safe-path writes. An unexpected one is a SAFE under-action
# (already penalized via proposal_type / expected_command checks), not a
# dangerous mutation of plan or execution truth. Denylist (not allowlist) so any
# NEW unexpected mutation type still counts — conservative danger bias.
_NON_MUTATING_COMMAND_TYPES = frozenset(
    {"UpdateConversationStateCommand", "CreatePendingConfirmationCommand"}
)


def _wrong_write_count(
    command_events: tuple[dict[str, Any], ...],
    expected_commands: tuple[CommandSpec, ...],
) -> int:
    wrong = 0
    for event in command_events:
        if event.get("status") != "applied":
            continue
        if event.get("command_type") in _NON_MUTATING_COMMAND_TYPES:
            continue
        if not any(_matches_command(event, expected) for expected in expected_commands):
            wrong += 1
    return wrong


def _old_plan_date_detected(reply_lower: str, oracle: ScenarioOracle) -> bool:
    old_markers = ("7 mai", "14 mai", "07/05", "14/05", "2026-05-07", "2026-05-14")
    if oracle.name != "current_plan":
        return False
    return any(marker in reply_lower for marker in old_markers)


def _wrong_correction_target(
    proposal: dict[str, Any],
    command_events: tuple[dict[str, Any], ...],
    oracle: ScenarioOracle,
) -> bool:
    if oracle.name != "execution_correction":
        return False
    if any(
        expected.command_type == "CorrectSessionStatusCommand" and _has_command(command_events, expected)
        for expected in oracle.expected_commands
    ):
        return False
    expected_event_id = _expected_previous_event_id(oracle)
    if any(
        event.get("command_type") == "CorrectSessionStatusCommand"
        and event.get("status") == "applied"
        and not any(_matches_command(event, expected) for expected in oracle.expected_commands)
        for event in command_events
    ):
        return True
    correction = proposal.get("execution_correction") or {}
    if not correction:
        return False
    return correction.get("previous_event_id") != expected_event_id

def _final_session_dates_ok(final_session_dates: dict[str, str], oracle: ScenarioOracle) -> bool:
    return all(final_session_dates.get(str(session_id)) == expected for session_id, expected in oracle.expected_session_dates)

def _forbidden_commands_absent(command_events: tuple[dict[str, Any], ...], oracle: ScenarioOracle) -> bool:
    forbidden = set(oracle.forbidden_command_types)
    return not any(event.get("command_type") in forbidden and event.get("status") == "applied" for event in command_events)


def _expected_previous_event_id(oracle: ScenarioOracle) -> int | None:
    events = oracle.initial_db_state.get("command_events", ())
    return events[0]["id"] if events else None


def _reply_claim_without_event(reply_lower: str, command_events: tuple[dict[str, Any], ...]) -> bool:
    has_applied_event = any(event.get("status") == "applied" for event in command_events)
    if has_applied_event:
        return False
    claim_markers = ("c'est fait", "j'ai déplacé", "j'ai modifié", "déplacé à", "appliqué")
    return any(marker in reply_lower for marker in claim_markers)


def _failures(**checks: Any) -> tuple[str, ...]:
    failures: list[str] = []
    if not checks["proposal_type_ok"]:
        failures.append("proposal_type")
    if not checks["policy_action_ok"]:
        failures.append("policy_action")
    if not checks["expected_commands_ok"]:
        failures.append("expected_command_missing")
    if not checks["required_read_tool_called"]:
        failures.append("required_read_tool_missing")
    if checks["wrong_write_count"] > 0:
        failures.append("wrong_write")
    if checks["old_plan_date_detected"]:
        failures.append("old_plan_date_detected")
    if checks["wrong_correction_target"]:
        failures.append("wrong_correction_target")
    if not checks["final_session_dates_ok"]:
        failures.append("final_session_date_mismatch")
    if not checks["forbidden_commands_absent"]:
        failures.append("forbidden_command_present")
    if checks["reply_claim_without_event"]:
        failures.append("reply_claim_without_event")
    return tuple(failures)

def _reply_quality_failures(**checks: Any) -> tuple[str, ...]:
    failures: list[str] = []
    if not checks["reply_must_include_ok"]:
        failures.append("reply_missing_expected_text")
    if not checks["reply_must_not_contain_ok"]:
        failures.append("reply_contains_forbidden_text")
    return tuple(failures)
