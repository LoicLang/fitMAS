#!/usr/bin/env python3
"""Run the human coach smoke scenarios against multiple LLM providers."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROFILES = ("deepseek", "mistral", "gemini", "grok")
DEFAULT_SUITES = ("human",)
SUITE_CHOICES = ("human", "core", "daily", "extended", "all")
DEFAULT_PROFILE_MODELS = {
    "deepseek": "deepseek-v4-pro",
    "mistral": "mistral-small-2603",
    "gemini": "gemini-3.5-flash",
    "grok": "grok-4.3",
}
DEFAULT_PROFILE_REASONING_EFFORTS = {
    "mistral": "high",
    "gemini": "medium",
    "grok": "low",
}
DEFAULT_HUMAN_SCENARIOS = (
    "human_missed_yesterday_short",
    "human_done_finally",
    "ambiguous_this_to_friday",
    "swim_unavailable_two_weeks_human",
    "fatigue_keep_light",
    "pending_ok_accept",
    "ok_without_pending",
    "pending_modify_saturday",
    "add_hard_tomorrow_loaded",
)
PROFILE_KEY_ENVS = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "grok": ("XAI_API_KEY", "GROK_API_KEY"),
}
_SMOKE_OUTPUT_MARKERS = (
    "A+ API smoke:",
    "DB:",
    "API:",
    "log:",
    "prompt:",
    "turn#",
    "artifacts:",
    "WARN:",
    "fallback census:",
    "RESULT:",
    "server log:",
)


@dataclass(frozen=True)
class ProfileRun:
    profile: str
    suite: str
    status: str
    command: list[str]
    output_dir: Path
    duration_seconds: float
    returncode: int | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    missing_env: str | None = None
    scenarios: dict[str, dict[str, Any]] | None = None
    fallback_census: Any | None = None


def build_smoke_command(
    *,
    profile: str,
    suite: str,
    scenarios: tuple[str, ...],
    output_dir: Path,
    timeout: float,
    port: int,
) -> list[str]:
    command = [
        str(ROOT / "scripts" / "smoke-a-plus-api"),
        "--skip-generated-week",
        "--db-path",
        str(output_dir / "smoke.db"),
        "--fallback-census-json",
        str(output_dir / "fallback_census.json"),
        "--keep-db",
        "--timeout",
        str(timeout),
        "--port",
        str(port),
    ]
    if suite == "daily":
        command.append("--daily")
    elif suite == "extended":
        command.append("--extended")
    elif suite not in {"human", "core"}:
        raise ValueError(f"Unknown smoke suite: {suite}")
    for scenario in scenarios:
        command.extend(["--scenario", scenario])
    return command


def extract_scenario_outputs(stdout: str) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    current_name: str | None = None
    current: dict[str, Any] | None = None
    assistant_open = False
    for line in stdout.splitlines():
        if line.startswith("SCENARIO "):
            current_name = line.removeprefix("SCENARIO ").strip()
            current = {
                "assistant_messages": [],
                "reasons": [],
                "warnings": [],
                "status": None,
                "prompt": "",
                "turns": [],
                "artifacts": {},
            }
            scenarios[current_name] = current
            assistant_open = False
            continue
        if current is None:
            continue
        if line.startswith("prompt: "):
            current["prompt"] = line.removeprefix("prompt: ").strip()
            assistant_open = False
        elif line.startswith("turn#"):
            _, _, turn_message = line.partition(":")
            current["turns"].append(turn_message.strip())
            assistant_open = False
        elif line.startswith("assistant: "):
            current["assistant_messages"].append(line.removeprefix("assistant: ").strip())
            assistant_open = True
        elif line.startswith("artifacts:"):
            current["artifacts"] = _parse_artifacts_line(line)
            assistant_open = False
        elif line == "OK":
            current["status"] = "OK"
            assistant_open = False
        elif line == "FAIL":
            current["status"] = "FAIL"
            assistant_open = False
        elif line.startswith("FAIL:"):
            current["status"] = "FAIL"
            current["reasons"].append(line.removeprefix("FAIL:").strip())
            assistant_open = False
        elif line.startswith("WARN:"):
            current["warnings"].append(line.removeprefix("WARN:").strip())
            assistant_open = False
        elif line.startswith(_SMOKE_OUTPUT_MARKERS):
            assistant_open = False
        elif line.startswith("- ") and current["status"] == "FAIL":
            current["reasons"].append(line.removeprefix("- ").strip())
        elif assistant_open and current["assistant_messages"]:
            current["assistant_messages"][-1] = f"{current['assistant_messages'][-1]}\n{line}"
    for scenario in scenarios.values():
        scenario["assistant_messages"] = [
            str(message).strip() for message in scenario.get("assistant_messages", [])
        ]
    return scenarios


def status_for_completed_run(
    returncode: int,
    scenarios: dict[str, dict[str, Any]],
    *,
    review_only: bool,
) -> str:
    if returncode == 0:
        return "ok"
    if review_only and scenarios and not _has_infra_failure(scenarios):
        return "reviewed"
    return "failed"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run coach smoke scenarios across DeepSeek, Mistral, Gemini, and Grok."
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=DEFAULT_PROFILES,
        help="Provider profile to run. Repeatable. Defaults to all four.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario name to run. Repeatable. Defaults to each selected suite's scenario set.",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=SUITE_CHOICES,
        help="Smoke suite to run: human, core, daily, extended, or all. Repeatable. Defaults to human.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / f".tmp-smoke-provider-matrix-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        help="Directory where per-provider outputs are written.",
    )
    parser.add_argument("--timeout", type=float, default=180.0, help="Seconds per API call in the smoke runner.")
    parser.add_argument("--port", type=int, default=8073, help="First localhost port to try.")
    parser.add_argument(
        "--model",
        action="append",
        metavar="PROFILE=MODEL",
        help="Override one provider model for this run, e.g. --model grok=grok-4.3.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print and persist commands without calling providers.")
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Collect replies/actions without failing the matrix on business expectation failures.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    profiles = tuple(args.profile or DEFAULT_PROFILES)
    suites = _expand_suites(args.suite)
    explicit_scenarios = tuple(args.scenario or ())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model_overrides = _parse_model_overrides(args.model or [])

    runs: list[ProfileRun] = []
    suite_scenarios: dict[str, tuple[str, ...]] = {}
    run_index = 0
    for suite in suites:
        scenarios = scenario_names_for_suite(suite, explicit_scenarios)
        suite_scenarios[suite] = scenarios
        for profile in profiles:
            profile_dir = output_dir / profile / suite
            profile_dir.mkdir(parents=True, exist_ok=True)
            command = build_smoke_command(
                profile=profile,
                suite=suite,
                scenarios=scenarios if suite == "human" or explicit_scenarios else (),
                output_dir=profile_dir,
                timeout=args.timeout,
                port=args.port + run_index,
            )
            run_index += 1
            if args.dry_run:
                runs.append(
                    ProfileRun(
                        profile=profile,
                        suite=suite,
                        status="dry_run",
                        command=command,
                        output_dir=profile_dir,
                        duration_seconds=0.0,
                        model=_model_for_profile(profile, model_overrides),
                        reasoning_effort=_reasoning_effort_for_profile(profile),
                        scenarios={name: {"assistant_messages": [], "reasons": [], "status": "DRY_RUN"} for name in scenarios},
                    )
                )
                continue
            missing_env = _missing_env_for_profile(profile)
            if missing_env:
                runs.append(
                    ProfileRun(
                        profile=profile,
                        suite=suite,
                        status="skipped",
                        command=command,
                        output_dir=profile_dir,
                        duration_seconds=0.0,
                        model=_model_for_profile(profile, model_overrides),
                        reasoning_effort=_reasoning_effort_for_profile(profile),
                        missing_env=missing_env,
                        scenarios={name: {"assistant_messages": [], "reasons": [f"missing {missing_env}"], "status": "SKIPPED"} for name in scenarios},
                    )
                )
                continue
            runs.append(
                _run_profile(
                    profile,
                    suite,
                    command,
                    profile_dir,
                    model_overrides.get(profile),
                    review_only=args.review_only,
                )
            )

    _write_summary(output_dir, runs, suite_scenarios)
    _print_summary(output_dir, runs)
    return 1 if any(run.status == "failed" for run in runs) else 0


def _run_profile(
    profile: str,
    suite: str,
    command: list[str],
    output_dir: Path,
    model: str | None,
    *,
    review_only: bool,
) -> ProfileRun:
    env = os.environ.copy()
    env["FITMAS_LLM_PROFILE"] = profile
    if model:
        env["FITMAS_LLM_MODEL"] = model
    resolved_model = _model_for_profile(profile, {profile: model} if model else {})
    reasoning_effort = _reasoning_effort_for_profile(profile)
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    duration = perf_counter() - started
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    scenarios = extract_scenario_outputs(completed.stdout)
    fallback_census = _read_json(output_dir / "fallback_census.json")
    run = ProfileRun(
        profile=profile,
        suite=suite,
        status=status_for_completed_run(completed.returncode, scenarios, review_only=review_only),
        command=command,
        output_dir=output_dir,
        duration_seconds=duration,
        returncode=completed.returncode,
        model=resolved_model,
        reasoning_effort=reasoning_effort,
        scenarios=scenarios,
        fallback_census=fallback_census,
    )
    (output_dir / "run.json").write_text(
        json.dumps(_profile_run_payload(run), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return run


def _parse_model_overrides(raw_items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in raw_items:
        if "=" not in raw:
            raise SystemExit(f"Invalid --model override: {raw}. Expected PROFILE=MODEL.")
        profile, model = raw.split("=", 1)
        profile = profile.strip()
        model = model.strip()
        if profile not in DEFAULT_PROFILES:
            raise SystemExit(f"Invalid --model profile: {profile}. Expected one of {', '.join(DEFAULT_PROFILES)}.")
        if not model:
            raise SystemExit(f"Invalid --model override for {profile}: empty model.")
        overrides[profile] = model
    return overrides


def _expand_suites(raw_suites: list[str] | None) -> tuple[str, ...]:
    selected: list[str] = []
    for suite in raw_suites or list(DEFAULT_SUITES):
        expanded = ("human", "core", "daily", "extended") if suite == "all" else (suite,)
        for item in expanded:
            if item not in selected:
                selected.append(item)
    return tuple(selected)


def scenario_names_for_suite(
    suite: str,
    explicit_scenarios: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if explicit_scenarios:
        return explicit_scenarios
    if suite == "human":
        return DEFAULT_HUMAN_SCENARIOS
    if suite == "core":
        return _scenario_names_from_smoke_module("SCENARIOS")
    if suite == "daily":
        return _scenario_names_from_smoke_module("DAILY_SCENARIOS")
    if suite == "extended":
        return _scenario_names_from_smoke_module("EXTENDED_SCENARIOS")
    raise ValueError(f"Unknown smoke suite: {suite}")


def _scenario_names_from_smoke_module(attribute: str) -> tuple[str, ...]:
    module = _load_smoke_a_plus_module()
    scenarios = getattr(module, attribute)
    return tuple(str(scenario.name) for scenario in scenarios)


def _load_smoke_a_plus_module() -> Any:
    module_name = "_fitmas_smoke_a_plus_api"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / "smoke_a_plus_api.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load smoke_a_plus_api.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _model_for_profile(profile: str, model_overrides: dict[str, str]) -> str:
    return model_overrides.get(profile) or os.getenv("FITMAS_LLM_MODEL") or os.getenv(
        f"FITMAS_{profile.upper()}_MODEL",
        DEFAULT_PROFILE_MODELS[profile],
    )


def _reasoning_effort_for_profile(profile: str) -> str | None:
    raw = (
        os.getenv(f"FITMAS_{profile.upper()}_REASONING_EFFORT")
        or os.getenv("FITMAS_LLM_REASONING_EFFORT")
        or DEFAULT_PROFILE_REASONING_EFFORTS.get(profile)
    )
    normalized = str(raw or "").strip().lower()
    return normalized or None


def _missing_env_for_profile(profile: str) -> str | None:
    env_names = PROFILE_KEY_ENVS[profile]
    if any(os.getenv(env_name) for env_name in env_names):
        return None
    return "|".join(env_names)


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_summary(
    output_dir: Path,
    runs: list[ProfileRun],
    suite_scenarios: dict[str, tuple[str, ...]],
) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profiles": [_profile_run_payload(run) for run in runs],
        "suites": {suite: list(scenarios) for suite, scenarios in suite_scenarios.items()},
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Coach Provider Matrix",
        "",
        f"Output: `{output_dir}`",
        "",
        "| Suite | Provider | Status | Return code | Duration | Model | Reasoning | Output |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for run in runs:
        returncode = "" if run.returncode is None else str(run.returncode)
        lines.append(
            f"| {run.suite} | {run.profile} | {run.status} | {returncode} | {run.duration_seconds:.1f}s | "
            f"{run.model or ''} | {run.reasoning_effort or ''} | `{run.output_dir}` |"
        )
    lines.append("")
    lines.append("## Scenario Replies")
    for suite, scenarios in suite_scenarios.items():
        lines.append("")
        lines.append(f"### Suite {suite}")
        suite_runs = [run for run in runs if run.suite == suite]
        for scenario in scenarios:
            lines.append("")
            lines.append(f"#### {scenario}")
            for run in suite_runs:
                scenario_result = (run.scenarios or {}).get(scenario, {})
                assistant_messages = scenario_result.get("assistant_messages") or []
                status = scenario_result.get("status") or "UNKNOWN"
                reply = assistant_messages[-1] if assistant_messages else ""
                reasons = "; ".join(scenario_result.get("reasons") or [])
                artifacts = _format_artifacts_for_summary(scenario_result.get("artifacts") or {})
                detail = reply or reasons
                suffix = f" | {artifacts}" if artifacts else ""
                lines.append(f"- {run.profile}: {status}{suffix} - {detail}")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _profile_run_payload(run: ProfileRun) -> dict[str, Any]:
    return {
        "profile": run.profile,
        "suite": run.suite,
        "status": run.status,
        "returncode": run.returncode,
        "duration_seconds": round(run.duration_seconds, 3),
        "command": run.command,
        "output_dir": str(run.output_dir),
        "model": run.model,
        "reasoning_effort": run.reasoning_effort,
        "missing_env": run.missing_env,
        "scenarios": run.scenarios or {},
        "fallback_census": run.fallback_census,
    }


def _print_summary(output_dir: Path, runs: list[ProfileRun]) -> None:
    print(f"output: {output_dir}")
    for run in runs:
        suffix = f" missing={run.missing_env}" if run.missing_env else ""
        print(f"{run.profile}/{run.suite}: {run.status}{suffix}")


def _parse_artifacts_line(line: str) -> dict[str, Any]:
    raw = line.removeprefix("artifacts:").strip()
    artifacts: dict[str, Any] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        value = value.rstrip(",")
        if key == "events":
            artifacts["events_delta"] = _parse_int(value)
        elif key == "pending":
            artifacts["pending_delta"] = _parse_int(value)
        elif key == "mode":
            artifacts["response_mode"] = "" if value == "-" else value
        elif key == "mutation_applied":
            artifacts["mutation_applied"] = value.lower() in {"1", "true", "yes", "on"}
        elif key == "session_changes":
            artifacts["session_changes"] = _parse_int(value)
        else:
            artifacts[key] = _parse_scalar(value)
    return artifacts


def _parse_int(value: str) -> int:
    return int(value)


def _parse_scalar(value: str) -> Any:
    normalized = value.lower()
    if normalized in {"true", "false"}:
        return normalized == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _has_infra_failure(scenarios: dict[str, dict[str, Any]]) -> bool:
    for scenario in scenarios.values():
        artifacts = scenario.get("artifacts") or {}
        if str(artifacts.get("response_mode") or "").strip() == "llm_unavailable":
            return True
        for reason in scenario.get("reasons") or []:
            normalized = str(reason).strip().lower()
            if "http/llm error" in normalized or "llm_unavailable" in normalized:
                return True
    return False


def _format_artifacts_for_summary(artifacts: dict[str, Any]) -> str:
    if not artifacts:
        return ""
    parts: list[str] = []
    if "response_mode" in artifacts:
        parts.append(f"mode={artifacts['response_mode'] or '-'}")
    if "events_delta" in artifacts:
        parts.append(f"events=+{artifacts['events_delta']}")
    if "pending_delta" in artifacts:
        parts.append(f"pending=+{artifacts['pending_delta']}")
    if "mutation_applied" in artifacts:
        parts.append(f"mutation={artifacts['mutation_applied']}")
    if "session_changes" in artifacts:
        parts.append(f"sessions={artifacts['session_changes']}")
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
