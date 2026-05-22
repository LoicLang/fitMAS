from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
    ROOT / "scripts",
)


def _python_like_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".py" or (root.name == "scripts" and path.suffix == ""):
            files.append(path)
    return sorted(files)


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_12a_claim_guard_root_module_is_deleted() -> None:
    assert not (SRC / "claim_guard.py").exists()


def test_12a_no_python_imports_use_root_claim_guard() -> None:
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in _python_like_files(root):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            if "fitmas.claim_guard" in imports:
                offenders.append(f"{path.relative_to(ROOT)}: fitmas.claim_guard")

    assert offenders == []


def test_12a_claim_guard_api_lives_in_output_verifier() -> None:
    source = (SRC / "decision" / "output_verifier.py").read_text(encoding="utf-8")

    assert "def looks_like_action_claim(" in source
    assert "def build_claim_repair_prompt(" in source
    assert "def outage_fallback_reply(" in source
