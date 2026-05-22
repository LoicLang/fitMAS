from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPT = ROOT / "scripts" / "decision-runtime-conversation-bridge-census"
MODULE = ROOT / "scripts" / "decision_runtime_conversation_bridge_census.py"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _load_module():
    spec = importlib.util.spec_from_file_location("conversation_bridge_census", MODULE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_10f_conversation_bridge_census_tracks_remaining_runtime_bridges() -> None:
    census_module = _load_module()

    census = census_module.build_census(ROOT)
    by_path = {entry["path"]: entry for entry in census["modules"]}

    assert census["module_count"] >= 8
    assert by_path["legacy/conversation_decide_bridge.py"]["status"] == "deleted"
    assert by_path["legacy/conversation_understanding_bridge.py"]["status"] == "deleted"


def test_10f_census_cli_writes_json(tmp_path: Path) -> None:
    output = tmp_path / "conversation-bridge-census.json"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json-out", str(output)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "runtime_active_count=" in result.stdout
    payload = json.loads(output.read_text())
    assert payload["module_count"] >= 8
    assert payload["runtime_active_count"] == 0


def test_10f_activity_and_clarification_live_in_decision_not_legacy() -> None:
    router = _source("decision/turn_router.py")
    early_reply_route = _source("decision/turn_pre_understanding_reply_route.py")

    assert "turn_pre_understanding_reply_route" in router
    assert "from fitmas.decision import activity_highlight" in early_reply_route
    assert "from fitmas.decision import clarification_reply" in early_reply_route
    assert "conversation_activity_highlight_bridge" not in router
    assert "conversation_canonical_clarification_bridge" not in router
    assert not (SRC / "legacy/conversation_activity_highlight_bridge.py").exists()
    assert not (SRC / "legacy/conversation_canonical_clarification_bridge.py").exists()


def test_10f_decision_artifact_helpers_are_deleted_with_artifact_owner() -> None:
    pipeline = _source("decision/conversation_pipeline.py")

    assert "conversation_decision_bridge" not in pipeline
    assert not (SRC / "legacy/conversation_decision_bridge.py").exists()
    assert not (SRC / "legacy/coach_decision_artifact.py").exists()
    assert "legacy_decision_artifact" not in pipeline


def test_10f_coach_decision_reply_helpers_are_not_legacy_or_readonly_owned() -> None:
    pipeline = _source("decision/conversation_pipeline.py")
    readonly = _source("decision/readonly_reply.py")
    command_reply = _source("decision/command_reply.py")

    assert "conversation_coach_decision_reply_bridge" not in pipeline
    assert not (SRC / "legacy/conversation_coach_decision_reply_bridge.py").exists()
    assert "def can_route_coach_decision_reply(" not in readonly
    assert "def compose_coach_decision_reply(" not in readonly
    assert "def compose_understanding_command_reply(" not in readonly
    assert "def compose_understanding_command_reply(" in command_reply


def test_10h_readonly_reply_lives_in_decision_not_legacy() -> None:
    router = _source("decision/turn_router.py")
    understanding_route = _source("decision/turn_understanding_route.py")
    readonly = _source("decision/readonly_reply.py")

    assert "turn_understanding_route" in router
    assert "from fitmas.decision import readonly_reply" in understanding_route
    assert "conversation_canonical_readonly_bridge" not in router
    assert "conversation_readonly_reply_bridge" not in router
    assert not (SRC / "legacy/conversation_canonical_readonly_bridge.py").exists()
    assert not (SRC / "legacy/conversation_readonly_reply_bridge.py").exists()
    assert "def should_use_canonical_readonly_without_legacy(" in readonly
    assert "def compose_canonical_readonly_reply(" in readonly
    assert "def compose_no_change_reply_for_turn(" in readonly
    assert "def compose_coach_decision_reply(" not in readonly


def test_10i_understanding_runtime_lives_in_decision_not_legacy() -> None:
    router = _source("decision/turn_router.py")
    understanding_route = _source("decision/turn_understanding_route.py")
    runtime = _source("decision/understanding_runtime.py")

    assert "turn_understanding_route" in router
    assert "from fitmas.decision import understanding_runtime" in understanding_route
    assert "conversation_understanding_bridge" not in router
    assert not (SRC / "legacy/conversation_understanding_bridge.py").exists()
    assert "def run_canonical_understanding_shadow(" in runtime
    assert "def should_use_canonical_understanding_without_legacy(" in runtime
    assert "def trace_canonical_understanding_pivot(" in runtime
    assert "coach_decision_artifact_from_understanding" not in runtime


def test_10i_conversation_bridge_census_only_tracks_legacy_decide_active() -> None:
    census_module = _load_module()

    census = census_module.build_census(ROOT)
    by_path = {entry["path"]: entry for entry in census["modules"]}

    assert census["runtime_active_count"] == 0
    assert census["deleted_count"] >= 9
    assert by_path["legacy/conversation_understanding_bridge.py"]["status"] == "deleted"
    assert by_path["legacy/conversation_decide_bridge.py"]["status"] == "deleted"


def test_10j_coach_decision_runtime_lives_in_decision_not_legacy_bridge() -> None:
    router = _source("decision/turn_router.py")
    understanding_route = _source("decision/turn_understanding_route.py")
    runtime = _source("decision/coach_decision_runtime.py")

    assert "turn_understanding_route" in router
    assert "from fitmas.decision import coach_decision_runtime" in understanding_route
    assert "conversation_decide_bridge" not in router
    assert not (SRC / "legacy/conversation_decide_bridge.py").exists()
    assert "def build_legacy_coach_decision_request(" not in runtime
    assert "def run_legacy_coach_decision(" not in runtime
    assert "def legacy_provider_allowed_for_turn(" not in runtime
    assert not (SRC / "legacy/coach_decision_provider.py").exists()
    assert "def canonical_provider_clarification_outcome(" in runtime


def test_10j_conversation_bridge_census_has_no_runtime_active_bridge() -> None:
    census_module = _load_module()

    census = census_module.build_census(ROOT)
    by_path = {entry["path"]: entry for entry in census["modules"]}

    assert census["runtime_active_count"] == 0
    assert census["deleted_count"] == census["module_count"]
    assert by_path["legacy/conversation_decide_bridge.py"]["status"] == "deleted"
