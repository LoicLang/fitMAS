from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
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
    if args.dry_run:
        _print_dry_run(plan)
        if args.report_path:
            Path(args.report_path).write_text(_dry_run_report(plan), encoding="utf-8")
        return 0
    if args.provider == "fake":
        records = run_fake_matrix(plan)
        return _finish(records, args.report_path)
    try:
        records = run_provider_matrix(plan)
    except ProviderConfigError as exc:
        print(str(exc))
        return 2
    return _finish(records, args.report_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Runtime V0 scenario matrix.")
    parser.add_argument("--provider", choices=ALL_PROVIDERS)
    parser.add_argument("--scenario", choices=DEFAULT_SCENARIOS)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--db-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path")
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
        failures = (f"provider_error:{type(exc).__name__}",)
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
    )


def _run_fake_item(item: MatrixPlanItem, db_path: Path) -> MatrixRunRecord:
    scenario = scenario_by_name(item.scenario)
    seed_db(db_path, scenario.initial_db_state)
    turn_id = f"{item.provider}-{item.scenario}-{item.repetition}"
    start = time.perf_counter()
    verdicts = _run_fake_scenario(db_path, scenario, turn_id)
    latency_ms = round((time.perf_counter() - start) * 1000)
    failures = tuple(failure for verdict in verdicts for failure in verdict.failures)
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
    }
    return scripts[scenario_name]


def _db_name(item: MatrixPlanItem) -> str:
    return f"{item.provider}-{item.scenario}-{item.repetition}.db"


def _finish(records: list[MatrixRunRecord], report_path: str | None) -> int:
    for record in records:
        status = "PASS" if record.success else f"FAIL {','.join(record.failures)}"
        print(f"{record.provider}/{record.scenario}/{record.repetition} {status}")
    report = render_markdown_report(records)
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0 if all(record.success for record in records) else 1


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
