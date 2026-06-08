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


def test_11o_grounding_contract_leaves_root_for_decision_package() -> None:
    assert not (SRC / "grounding_contract.py").exists()
    assert (SRC / "decision" / "grounding.py").exists()


def test_11o_no_python_imports_use_root_grounding_contract() -> None:
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in _python_like_files(root):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            if "fitmas.grounding_contract" in imports:
                offenders.append(f"{path.relative_to(ROOT)}: fitmas.grounding_contract")

    assert offenders == []


def test_11o_decision_grounding_has_no_llm_or_db_imports() -> None:
    imports = _imports(SRC / "decision" / "grounding.py")

    assert not any(module.startswith("fitmas.legacy.llm") for module in imports)
    assert "fitmas.legacy.core.db" not in imports
    assert "sqlalchemy.orm" not in imports
