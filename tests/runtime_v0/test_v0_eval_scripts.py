import subprocess
import sys

from scripts.v0_eval.report import MatrixRunRecord, render_markdown_report
from scripts.v0_eval.run_matrix import build_run_plan


def test_build_run_plan_defaults_to_five_scenarios_four_target_providers():
    plan = build_run_plan(repetitions=1)

    assert len(plan) == 20
    assert {item.scenario for item in plan} == {
        "current_plan",
        "tomorrow",
        "skipped_yesterday",
        "execution_correction",
        "followup_planning_turn1",
    }
    assert {item.provider for item in plan} == {"gemini", "grok", "deepseek", "mistral"}


def test_build_run_plan_filters_provider_and_scenario():
    plan = build_run_plan(provider="deepseek", scenario="tomorrow", repetitions=2)

    assert [(item.provider, item.scenario, item.repetition) for item in plan] == [
        ("deepseek", "tomorrow", 1),
        ("deepseek", "tomorrow", 2),
    ]


def test_report_renders_success_table_and_failures():
    markdown = render_markdown_report(
        [
            MatrixRunRecord(
                scenario="current_plan",
                provider="deepseek",
                repetition=1,
                success=True,
                latency_ms=1200,
                tokens_in=100,
                tokens_out=40,
                failures=(),
                turn_id="turn-1",
            ),
            MatrixRunRecord(
                scenario="tomorrow",
                provider="gemini",
                repetition=1,
                success=False,
                latency_ms=2200,
                tokens_in=120,
                tokens_out=45,
                failures=("required_read_tool_missing",),
                turn_id="turn-2",
            ),
        ]
    )

    assert "| current_plan | deepseek | 1/1 |" in markdown
    assert "| tomorrow | gemini | 0/1 |" in markdown
    assert "required_read_tool_missing" in markdown
    assert "turn-2" in markdown


def test_run_matrix_dry_run_prints_planned_runs_without_provider_calls():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/v0_eval/run_matrix.py",
            "--dry-run",
            "--repetitions",
            "1",
            "--provider",
            "deepseek",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "DRY RUN" in completed.stdout
    assert "deepseek/current_plan/1" in completed.stdout
    assert "deepseek/followup_planning_turn1/1" in completed.stdout
    assert "provider calls: 0" in completed.stdout


def test_run_matrix_fake_provider_executes_offline_and_writes_report(tmp_path):
    report_path = tmp_path / "v0-fake-report.md"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/v0_eval/run_matrix.py",
            "--provider",
            "fake",
            "--repetitions",
            "1",
            "--report-path",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "fake/current_plan/1 PASS" in completed.stdout
    report = report_path.read_text(encoding="utf-8")
    assert "| current_plan | fake | 1/1 |" in report
    assert "No failures." in report


def test_run_matrix_real_provider_reports_missing_api_key(tmp_path):
    env = {key: value for key, value in __import__("os").environ.items() if key != "DEEPSEEK_API_KEY"}
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/v0_eval/run_matrix.py",
            "--provider",
            "deepseek",
            "--scenario",
            "current_plan",
            "--repetitions",
            "1",
            "--report-path",
            str(tmp_path / "report.md"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "missing_env:DEEPSEEK_API_KEY" in completed.stdout
