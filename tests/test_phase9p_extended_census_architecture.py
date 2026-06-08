from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "phase9p_smoke_a_plus_api",
        ROOT / "scripts" / "smoke_a_plus_api.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extended_scenario_surface_exists() -> None:
    smoke = _load_smoke_module()

    assert hasattr(smoke, "EXTENDED_SCENARIOS")
    assert len(smoke.EXTENDED_SCENARIOS) >= 18


def test_extended_cli_flag_is_exposed() -> None:
    smoke = _load_smoke_module()

    args = smoke.parse_args(["--extended", "--skip-generated-week"])

    assert args.extended is True


def test_extended_census_wrapper_exists_and_uses_all_census_inputs() -> None:
    wrapper = ROOT / "scripts" / "smoke-decision-runtime-extended-census"

    assert wrapper.exists()
    assert wrapper.stat().st_mode & 0o111

    source = wrapper.read_text()
    for marker in (
        "--fallback-census-json /tmp/fitmas-9p-core-census.json",
        "--daily",
        "--fallback-census-json /tmp/fitmas-9p-daily-census.json",
        "--extended",
        "--fallback-census-json /tmp/fitmas-9p-extended-census.json",
        "--json-out /tmp/fitmas-9p-global-summary.json",
    ):
        assert marker in source
    assert "--allow-fallbacks" not in source


def test_extended_scenario_names_do_not_duplicate_core_or_daily() -> None:
    smoke = _load_smoke_module()

    core = {scenario.name for scenario in smoke.SCENARIOS}
    daily = {scenario.name for scenario in smoke.DAILY_SCENARIOS}
    extended = [scenario.name for scenario in smoke.EXTENDED_SCENARIOS]

    assert len(extended) == len(set(extended))
    assert not set(extended) & core
    assert not set(extended) & daily


def test_extended_scenarios_cover_required_probe_groups() -> None:
    smoke = _load_smoke_module()
    descriptions = " ".join(
        f"{scenario.name} {scenario.description}" for scenario in smoke.EXTENDED_SCENARIOS
    )

    for marker in (
        "pending",
        "execution",
        "health",
        "availability",
        "read-only",
        "elliptical",
        "memory",
    ):
        assert marker in descriptions


def test_trivial_ack_turn_plan_uses_terminal_close_path() -> None:
    from fitmas.legacy.decision import turn_context

    assert turn_context.should_use_terminal_close_path(
        turn_plan=SimpleNamespace(
            primary_intent="trivial_ack",
            secondary_intents=(),
            has_plan_mutation=False,
        ),
        pending_confirmation=None,
        open_calibration_need=None,
    )
