from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_LLM_MODULES = {
    "calibration_llm.py": "fitmas.calibration_llm",
    "prompt_contracts.py": "fitmas.prompt_contracts",
    "prompt_observability.py": "fitmas.prompt_observability",
}
TARGET_LLM_MODULES = {
    "calibration.py",
    "prompt_contracts.py",
    "prompt_observability.py",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_11i_llm_support_modules_live_under_llm_package_only() -> None:
    target_dir = SRC / "llm"

    assert all((target_dir / filename).exists() for filename in TARGET_LLM_MODULES)
    assert [filename for filename in ROOT_LLM_MODULES if (SRC / filename).exists()] == []


def test_11i_no_python_imports_use_root_llm_support_modules() -> None:
    forbidden = set(ROOT_LLM_MODULES.values())
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            matched = sorted(module for module in imports if module in forbidden)
            if matched:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(matched)}")

    assert offenders == []
