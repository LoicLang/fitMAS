from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _backend_python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_10k_conversation_runtime_no_longer_builds_or_calls_coachdecision_provider() -> None:
    pipeline = _source("conversation_pipeline.py")
    runtime = _source("decision/coach_decision_runtime.py")
    contract = _source("conversation_contract.py")
    routes = _source("app/api/routes_messages.py")

    assert "LegacyCoachDecisionProvider" not in pipeline
    assert "default_legacy_decide" not in pipeline
    assert "build_legacy_coach_decision_request(" not in pipeline
    assert "run_legacy_coach_decision(" not in pipeline
    assert "dependencies.decide" not in pipeline

    assert "def build_legacy_coach_decision_request(" not in runtime
    assert "def run_legacy_coach_decision(" not in runtime
    assert "def legacy_provider_allowed_for_turn(" not in runtime
    assert "fitmas.legacy.coach_decision_provider" not in runtime

    assert "decide:" not in contract
    assert "default_legacy_decide as decide" not in routes
    assert not (SRC / "legacy/coach_decision_provider.py").exists()


def test_10k_no_backend_runtime_imports_coachdecision_provider_module() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        relative = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fitmas.legacy.coach_decision_provider":
                offenders.append(relative)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fitmas.legacy.coach_decision_provider":
                        offenders.append(relative)

    assert offenders == []
