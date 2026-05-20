from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text()


def _python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend((ROOT / root).rglob("*.py"))
    return sorted(files)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(SRC))
    except ValueError:
        return str(path.relative_to(ROOT))


def test_9u_llm_package_no_longer_aliases_to_decision_legacy() -> None:
    source = _source("llm/__init__.py")

    assert "sys.modules[__name__]" not in source
    assert "_decision_legacy.__path__" not in source


def test_9u_runtime_modules_do_not_import_broad_fitmas_llm() -> None:
    allowed = {
        "llm/decision_legacy.py",
        "llm/legacy_tool_loop.py",
        "llm/legacy_provider.py",
        "llm/legacy_schema_repair.py",
        "llm/legacy_onboarding.py",
        "llm/legacy_fact_memory.py",
        "llm/legacy_summaries.py",
    }
    offenders: list[str] = []
    for path in _python_files("backend/src/fitmas"):
        relative = _relative(path)
        if relative in allowed or relative.startswith("llm/prompts/"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fitmas.llm":
                offenders.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fitmas.llm":
                        offenders.append(f"{relative}:{node.lineno}")

    assert offenders == []


def test_9u_legacy_decision_contracts_do_not_import_fitmas_llm() -> None:
    source = _source("legacy/decision_contracts.py")

    assert "from fitmas.llm import" not in source
    assert "import fitmas.llm" not in source


def test_9u_legacy_provider_has_no_default_broad_llm_runtime_import() -> None:
    source = _source("legacy/coach_decision_provider.py")

    assert "from fitmas import llm" not in source
    assert "llm_runtime" not in source


def test_9u_legacy_provider_env_flag_is_default_off() -> None:
    source = _source("legacy/conversation_decide_bridge.py")

    assert "FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER" in source
    assert 'os.getenv("FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER") == "1"' in source


def test_9u_decision_legacy_stays_under_provider_compat_budget() -> None:
    line_count = len(_source("llm/decision_legacy.py").splitlines())

    assert line_count <= 500
