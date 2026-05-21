from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decision-runtime-planning-pending-census"
MODULE = ROOT / "scripts" / "decision_runtime_planning_pending_census.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("planning_pending_census", MODULE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_planning_pending_census_maps_runtime_callers_and_symbols() -> None:
    census_module = _load_module()

    census = census_module.build_census(ROOT)
    by_path = {entry["path"]: entry for entry in census["modules"]}

    planning = by_path["legacy/conversation_canonical_planning_bridge.py"]
    assert planning["owner"] == "planning"
    assert planning["status"] == "deleted"
    assert planning["runtime_importers"] == []
    assert planning["runtime_symbols"] == []

    pending = by_path["legacy/conversation_pending_bridge.py"]
    assert pending["owner"] == "pending"
    assert pending["status"] == "deleted"
    assert pending["runtime_importers"] == []
    assert pending["runtime_symbols"] == []

    reply_adapter = by_path["legacy/pending_reply_adapter.py"]
    assert reply_adapter["owner"] == "pending_reply"
    assert reply_adapter["status"] == "deleted"
    assert reply_adapter["runtime_importers"] == []


def test_planning_pending_census_cli_writes_json(tmp_path: Path) -> None:
    output = tmp_path / "census.json"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json-out", str(output)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "legacy/conversation_canonical_planning_bridge.py" in result.stdout
    assert "deleted_count=7" in result.stdout

    payload = json.loads(output.read_text())
    assert payload["module_count"] == 7
    assert payload["runtime_active_count"] == 0
    assert payload["legacy_internal_count"] == 0
    assert payload["test_only_count"] == 0
    assert payload["deleted_count"] == 7
    assert any(
        entry["path"] == "legacy/conversation_pending_bridge.py"
        and entry["status"] == "deleted"
        for entry in payload["modules"]
    )
