from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("scripts/decision-runtime-fallback-census-summary")


def test_fallback_census_summary_combines_reports_and_fails_closed(tmp_path: Path) -> None:
    first = tmp_path / "core.json"
    second = tmp_path / "daily.json"
    first.write_text(
        json.dumps(
            {
                "scenario_count": 2,
                "fallback_scenario_count": 1,
                "reports": [
                    {
                        "scenario": "move_hard_close",
                        "fallback_turn_count": 1,
                        "owner_counts": {"planning": 1},
                        "source_counts": {"canonical_planning_provider": 1},
                    },
                    {
                        "scenario": "lookup_current_plan",
                        "fallback_turn_count": 0,
                        "owner_counts": {},
                        "source_counts": {},
                    },
                ],
            }
        )
        + "\n"
    )
    second.write_text(
        json.dumps(
            {
                "scenario_count": 1,
                "fallback_scenario_count": 1,
                "reports": [
                    {
                        "scenario": "casual_banter",
                        "fallback_turn_count": 2,
                        "owner_counts": {"legacy_provider": 2},
                        "source_counts": {"legacy_decide": 2},
                    }
                ],
            }
        )
        + "\n"
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(first), str(second)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "scenario_count=3" in result.stdout
    assert "fallback_scenario_count=2" in result.stdout
    assert "owner planning=1" in result.stdout
    assert "owner legacy_provider=2" in result.stdout
    assert "source canonical_planning_provider=1" in result.stdout
    assert "source legacy_decide=2" in result.stdout
    assert "fallback scenario move_hard_close turns=1" in result.stdout
    assert "fallback scenario casual_banter turns=2" in result.stdout


def test_fallback_census_summary_allows_fallbacks_and_writes_json(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    output = tmp_path / "summary.json"
    report.write_text(
        json.dumps(
            {
                "scenario_count": 1,
                "fallback_scenario_count": 0,
                "reports": [
                    {
                        "scenario": "trip_memory_only",
                        "fallback_turn_count": 0,
                        "owner_counts": {},
                        "source_counts": {},
                    }
                ],
            }
        )
        + "\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(report),
            "--allow-fallbacks",
            "--json-out",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    payload = json.loads(output.read_text())
    assert payload["scenario_count"] == 1
    assert payload["fallback_scenario_count"] == 0
    assert payload["owner_counts"] == {}
    assert payload["source_counts"] == {}
