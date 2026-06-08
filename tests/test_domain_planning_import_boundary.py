from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_plan_patch_import_does_not_cycle_domain_planning_package() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fitmas.legacy.domain.planning.plan_patch import PlanPatch, validate_plan_patch; "
            "from fitmas.legacy.domain.planning import decide_plan_change; "
            "assert PlanPatch and validate_plan_patch and decide_plan_change",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "backend" / "src"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
