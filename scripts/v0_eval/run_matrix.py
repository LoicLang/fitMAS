from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
for path in (ROOT, BACKEND_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.reply import TECHNICAL_FALLBACK
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event
from scripts.v0_eval.oracle_compare import OracleVerdict, compare_persisted_turn
from scripts.v0_eval.provider_clients import MeteredLLMClient, ProviderConfigError, build_provider_client
from scripts.v0_eval.report import MatrixRunRecord, render_markdown_report
from scripts.v0_eval.scenarios import ScenarioOracle, scenario_by_name, seed_db

DEFAULT_SCENARIOS = (
    "current_plan",
    "tomorrow",
    "skipped_yesterday",
    "execution_correction",
    "followup_planning_turn1",
    "key_session_pending",
)
DEFAULT_PROVIDERS = ("gemini", "grok", "deepseek", "mistral")
ALL_PROVIDERS = (*DEFAULT_PROVIDERS, "fake")


@dataclass(frozen=True)
class MatrixPlanItem:
    provider: str
    scenario: str
    repetition: int
    db_path: Path | None = None


def build_run_plan(
    provider: str | None = None,
    scenario: str | None = None,
    repetitions: int = 3,
    db_path: Path | None = None,
) -> list[MatrixPlanItem]:
    providers = (provider,) if provider else DEFAULT_PROVIDERS
    scenarios = (scenario,) if scenario else DEFAULT_SCENARIOS
    return [
        MatrixPlanItem(
            provider=item_provider,
            scenario=item_scenario,
            repetition=repetition,
            db_path=db_path,
        )
        for item_provider in providers
        for item_scenario in scenarios
        for repetition in range(1, repetitions + 1)
    ]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan = build_run_plan(
        provider=args.provider,
        scenario=args.scenario,
        repetitions=args.repetitions,
        db_path=Path(args.db_path) if args.db_path else None,
    )
    export_dir = Path(args.export_dir) if args.export_dir else None
    if export_dir:
        plan = _with_export_dbs(plan, export_dir)
    if args.dry_run:
        _print_dry_run(plan)
        if args.report_path:
            Path(args.report_path).write_text(_dry_run_report(plan), encoding="utf-8")
        return 0
    if args.provider == "fake":
        records = run_fake_matrix(plan)
        return _finish(records, args.report_path, export_dir)
    try:
        records = run_provider_matrix(plan)
    except ProviderConfigError as exc:
        print(str(exc))
        return 2
    return _finish(records, args.report_path, export_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Runtime V0 scenario matrix.")
    parser.add_argument("--provider", choices=ALL_PROVIDERS)
    parser.add_argument("--scenario", choices=DEFAULT_SCENARIOS)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--db-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path")
    parser.add_argument("--export-dir")
    return parser


def run_fake_matrix(plan: list[MatrixPlanItem]) -> list[MatrixRunRecord]:
    with tempfile.TemporaryDirectory(prefix=".tmp-v0-matrix-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        return [
            _run_fake_item(item, item.db_path or tmp_root / _db_name(item))
            for item in plan
        ]


def run_provider_matrix(plan: list[MatrixPlanItem]) -> list[MatrixRunRecord]:
    clients = {provider: build_provider_client(provider) for provider in {item.provider for item in plan}}
    with tempfile.TemporaryDirectory(prefix=".tmp-v0-matrix-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        return [
            _run_provider_item(item, item.db_path or tmp_root / _db_name(item), clients[item.provider])
            for item in plan
        ]


def _run_provider_item(item: MatrixPlanItem, db_path: Path, client) -> MatrixRunRecord:
    scenario = scenario_by_name(item.scenario)
    seed_db(db_path, scenario.initial_db_state)
    turn_id = f"{item.provider}-{item.scenario}-{item.repetition}"
    meter = MeteredLLMClient(client, provider=item.provider, model=getattr(getattr(client, "profile", None), "model", "unknown"))
    start = time.perf_counter()
    try:
        verdicts = _run_provider_scenario(db_path, scenario, turn_id, meter)
        failures = tuple(failure for verdict in verdicts for failure in verdict.failures)
    except Exception as exc:
        verdicts = ()
        failures = (f"provider_error:{type(exc).__name__}",)
    metrics = _run_metrics(db_path, verdicts)
    return MatrixRunRecord(
        scenario=item.scenario,
        provider=item.provider,
        repetition=item.repetition,
        success=not failures,
        latency_ms=round((time.perf_counter() - start) * 1000),
        tokens_in=meter.tokens_in,
        tokens_out=meter.tokens_out,
        failures=failures,
        turn_id=turn_id,
        model=meter.model,
        db_path=str(db_path),
        triage=_triage(db_path, failures) if failures else (),
        **metrics,
    )


def _run_fake_item(item: MatrixPlanItem, db_path: Path) -> MatrixRunRecord:
    scenario = scenario_by_name(item.scenario)
    seed_db(db_path, scenario.initial_db_state)
    turn_id = f"{item.provider}-{item.scenario}-{item.repetition}"
    start = time.perf_counter()
    verdicts = _run_fake_scenario(db_path, scenario, turn_id)
    latency_ms = round((time.perf_counter() - start) * 1000)
    failures = tuple(failure for verdict in verdicts for failure in verdict.failures)
    metrics = _run_metrics(db_path, verdicts)
    return MatrixRunRecord(
        scenario=item.scenario,
        provider=item.provider,
        repetition=item.repetition,
        success=not failures,
        latency_ms=latency_ms,
        tokens_in=0,
        tokens_out=0,
        failures=failures,
        turn_id=turn_id,
        db_path=str(db_path),
        triage=_triage(db_path, failures) if failures else (),
        **metrics,
    )


def _run_provider_scenario(db_path: Path, scenario: ScenarioOracle, turn_id: str, client) -> tuple[OracleVerdict, ...]:
    deps = RuntimeDeps(db_path=db_path, coach_llm=client, reply_llm=client)
    handle_event(scenario.input_event, deps, turn_id=turn_id)
    verdicts = [compare_persisted_turn(db_path, turn_id, scenario)]
    if scenario.followup is not None:
        followup_id = f"{turn_id}-followup"
        handle_event(scenario.followup.input_event, deps, turn_id=followup_id)
        verdicts.append(compare_persisted_turn(db_path, followup_id, scenario.followup))
    return tuple(verdicts)


def _run_fake_scenario(
    db_path: Path,
    scenario: ScenarioOracle,
    turn_id: str,
) -> tuple[OracleVerdict, ...]:
    handle_event(scenario.input_event, _fake_deps(db_path, scenario.name), turn_id=turn_id)
    verdicts = [compare_persisted_turn(db_path, turn_id, scenario)]
    if scenario.followup is not None:
        followup_id = f"{turn_id}-followup"
        handle_event(
            scenario.followup.input_event,
            _fake_deps(db_path, scenario.followup.name),
            turn_id=followup_id,
        )
        verdicts.append(compare_persisted_turn(db_path, followup_id, scenario.followup))
    return tuple(verdicts)


def _fake_deps(db_path: Path, scenario_name: str) -> RuntimeDeps:
    coach_script, reply_text = _fake_script(scenario_name)
    return RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(coach_script),
        reply_llm=FakeLLMClient([LLMResponse(text=reply_text)]),
    )


def _fake_script(scenario_name: str) -> tuple[list[LLMResponse], str]:
    scripts = {
        "current_plan": (
            [
                LLMResponse(tool_calls=(ToolCall("get_current_plan", {"days": 7}),)),
                LLMResponse(text="22 Footing recup, 24 VMA courte, 26 Endurance."),
            ],
            "22 Footing recup. 24 VMA courte. 26 Endurance.",
        ),
        "tomorrow": (
            [
                LLMResponse(tool_calls=(ToolCall("get_plan_day", {"date": "2026-05-23"}),)),
                LLMResponse(text="23 Endurance facile."),
            ],
            "23 Endurance facile.",
        ),
        "skipped_yesterday": (
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_execution_update",
                            {"session_id": 66, "status": "skipped", "evidence": "pas fait hier"},
                        ),
                    )
                )
            ],
            "Noté pour hier.",
        ),
        "execution_correction": (
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
            ],
            "Corrigé: 25 minutes.",
        ),
        "followup_planning_turn1": (
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
            ],
            "Quelle séance veux-tu déplacer ?",
        ),
        "followup_planning_turn2": (
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
            ],
            "Déplacé à vendredi.",
        ),
        "key_session_pending": (
            [
                LLMResponse(tool_calls=(ToolCall("resolve_date_reference", {"weekday": "friday", "direction": "future"}),)),
                LLMResponse(tool_calls=(ToolCall("get_session", {"session_id": 61}),)),
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            "propose_plan_patch",
                            {
                                "operations": [{"kind": "move", "source_session_id": 61, "target_date": "2026-05-29"}],
                                "rationale": "déplacer la VMA à vendredi",
                            },
                        ),
                    )
                ),
            ],
            "Je dois confirmer avant de faire ça: déplacer la VMA à vendredi.",
        ),
    }
    return scripts[scenario_name]


def _db_name(item: MatrixPlanItem) -> str:
    return f"{item.provider}-{item.scenario}-{item.repetition}.db"


def _with_export_dbs(plan: list[MatrixPlanItem], export_dir: Path) -> list[MatrixPlanItem]:
    db_dir = export_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return [MatrixPlanItem(item.provider, item.scenario, item.repetition, db_dir / _db_name(item)) for item in plan]


def _finish(records: list[MatrixRunRecord], report_path: str | None, export_dir: Path | None = None) -> int:
    for record in records:
        status = "PASS" if record.success else f"FAIL {','.join(record.failures)}"
        print(f"{record.provider}/{record.scenario}/{record.repetition} {status}")
    report = render_markdown_report(records)
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    else:
        print(report)
    if export_dir:
        _write_export(export_dir, records, report)
    return 0 if all(record.success for record in records) else 1


def _write_export(export_dir: Path, records: list[MatrixRunRecord], report: str) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    responses = [_response_record(record) for record in records]
    (export_dir / "matrix-report.md").write_text(report, encoding="utf-8")
    (export_dir / "records.json").write_text(json.dumps([_record_json(record) for record in records], ensure_ascii=False, indent=2), encoding="utf-8")
    (export_dir / "responses.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2), encoding="utf-8")
    (export_dir / "responses.md").write_text(_responses_markdown(export_dir, report, responses), encoding="utf-8")


def _record_json(record: MatrixRunRecord) -> dict:
    return asdict(record)


def _run_metrics(db_path: Path, verdicts: tuple[OracleVerdict, ...]) -> dict:
    turns = _dump_turns(db_path) if db_path.exists() else []
    guard_reasons = [reason for turn in turns for reason in turn["guard_reasons"]]
    return {
        "turn_count": len(turns),
        "guard_block_count": sum(1 for turn in turns if not turn["guard_ok"]),
        "guard_repair_count": sum(1 for turn in turns if turn["result"].get("guard_repair_used")),
        "sanitized_fallback_count": sum(1 for turn in turns if turn["reply"] == TECHNICAL_FALLBACK),
        "raw_json_block_count": guard_reasons.count("raw_json_visible"),
        "truncated_reply_count": guard_reasons.count("truncated_reply"),
        "technical_id_block_count": guard_reasons.count("technical_id_visible"),
        "wrong_write_count": sum(verdict.wrong_write_count for verdict in verdicts),
        "old_plan_date_count": sum(1 for verdict in verdicts if verdict.old_plan_date_detected),
        "wrong_correction_target_count": sum(1 for verdict in verdicts if verdict.wrong_correction_target),
        "reply_claim_without_event_count": sum(1 for verdict in verdicts if verdict.reply_claim_without_event),
    }


def _triage(db_path: Path, failures: tuple[str, ...]) -> tuple[str, ...]:
    turns = _dump_turns(db_path) if db_path.exists() else []
    commands = _dump_command_events(db_path) if db_path.exists() else []
    lines = [f"failures={','.join(failures)}", f"probable={','.join(_probable_causes(failures))}"]
    for turn in turns:
        proposal_type = turn["result"].get("proposal_type") or turn["proposal"].get("type")
        policy_action = turn["result"].get("policy_action")
        tools = ",".join(call.get("name", "?") for call in turn["proposal"].get("tool_trace", [])) or "none"
        reasons = ",".join(turn["guard_reasons"]) or "none"
        lines.append(
            f"turn={turn['turn_id']} proposal={proposal_type} policy={policy_action} "
            f"tools={tools} guard={turn['guard_ok']} reasons={reasons}"
        )
        if turn["reply"]:
            lines.append(f"reply={turn['reply']}")
    if commands:
        lines.append(
            "commands="
            + ",".join(f"{event['command_type']}:{event['target_type']}:{event['target_id']}:{event['status']}" for event in commands)
        )
    return tuple(lines)


def _probable_causes(failures: tuple[str, ...]) -> tuple[str, ...]:
    causes: list[str] = []
    if {"proposal_type", "policy_action", "expected_command_missing"} & set(failures):
        causes.append("provider_missing_expected_artifact")
    if "reply_missing_expected_text" in failures or "reply_contains_forbidden_text" in failures:
        causes.append("reply_contract_mismatch")
    if {"wrong_write", "old_plan_date_detected", "wrong_correction_target", "reply_claim_without_event"} & set(failures):
        causes.append("runtime_safety_failure")
    if any(failure.startswith("provider_error:") for failure in failures):
        causes.append("provider_exception")
    return tuple(causes or ("unknown",))


def _response_record(record: MatrixRunRecord) -> dict:
    db_path = Path(record.db_path) if record.db_path else None
    return _record_json(record) | {
        "turns": _dump_turns(db_path) if db_path else [],
        "command_events": _dump_command_events(db_path) if db_path else [],
    }


def _dump_turns(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            select t.id, t.event_id, e.text as user_text, t.reply, t.provider, t.model, t.guard_ok,
            t.proposal_json, t.policy_json, t.result_json, t.guard_reasons_json
            from v0_turns t left join v0_input_events e on e.id = t.event_id
            where t.event_id is not null order by t.id
            """
        ).fetchall()
    return [
        {
            "turn_id": row["id"], "event_id": row["event_id"], "user_text": row["user_text"], "reply": row["reply"],
            "provider": row["provider"], "model": row["model"], "guard_ok": bool(row["guard_ok"]),
            "guard_reasons": _loads(row["guard_reasons_json"], []), "proposal": _loads(row["proposal_json"], {}),
            "policy": _loads(row["policy_json"], {}), "result": _loads(row["result_json"], {}),
        }
        for row in rows
    ]


def _dump_command_events(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("select * from v0_command_events order by id").fetchall()
    return [
        {
            "id": row["id"], "turn_id": row["turn_id"], "command_type": row["command_type"], "target_type": row["target_type"],
            "target_id": row["target_id"], "status": row["status"], "reason": row["reason"],
            "before": _loads(row["before_json"], {}), "after": _loads(row["after_json"], {}), "created_at": row["created_at"],
        }
        for row in rows
    ]


def _loads(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _responses_markdown(export_dir: Path, report: str, responses: list[dict]) -> str:
    lines = ["# Runtime V0 Provider Responses", "", f"Export: `{export_dir}`", "", report, "## Responses", ""]
    for item in responses:
        status = "PASS" if item["success"] else "FAIL " + ",".join(item["failures"])
        lines.extend([f"### {item['provider']} / {item['scenario']} - {status}", "", f"DB: `{item['db_path']}`", ""])
        for turn in item["turns"]:
            proposal_type = turn["result"].get("proposal_type") or turn["proposal"].get("type")
            policy_action = turn["result"].get("policy_action")
            tools = ", ".join(call.get("name", "?") for call in turn["proposal"].get("tool_trace", [])) or "none"
            lines.extend([f"- turn: `{turn['turn_id']}`", f"- user: {turn['user_text']}", f"- proposal/policy: `{proposal_type}` / `{policy_action}`", f"- tools: {tools}", "- reply:", "", "```text", turn["reply"] or "", "```", ""])
        if item["command_events"]:
            lines.append("Commands:")
            lines.extend(f"- `{event['command_type']}` {event['target_type']}:{event['target_id']} {event['status']} - {event['reason']}" for event in item["command_events"])
            lines.append("")
    return "\n".join(lines)


def _print_dry_run(plan: list[MatrixPlanItem]) -> None:
    print("DRY RUN")
    for item in plan:
        print(f"{item.provider}/{item.scenario}/{item.repetition}")
    print("provider calls: 0")


def _dry_run_report(plan: list[MatrixPlanItem]) -> str:
    lines = ["# Runtime V0 Matrix Dry Run", ""]
    for item in plan:
        lines.append(f"- `{item.provider}/{item.scenario}/{item.repetition}`")
    lines.append("")
    lines.append("provider calls: 0")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
