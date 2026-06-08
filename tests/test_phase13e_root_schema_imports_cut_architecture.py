from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = [
    ROOT / "backend" / "src",
    ROOT / "tests",
    ROOT / "scripts",
]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return sorted(files)


def _imports_root_schema(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fitmas.schema":
                    hits.append("import fitmas.schema")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "fitmas":
                for alias in node.names:
                    if alias.name == "schema":
                        hits.append("from fitmas import schema")
            elif node.module == "fitmas.schema":
                hits.append("from fitmas.schema import")
    return hits


def test_13e_no_code_imports_root_schema_module() -> None:
    offenders: list[str] = []
    for path in _python_files():
        hits = _imports_root_schema(path)
        if hits:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(set(hits))}")

    assert offenders == []


def test_13e_core_db_registers_tables_from_core_orm() -> None:
    source = (ROOT / "backend" / "src" / "fitmas" / "core" / "db.py").read_text(encoding="utf-8")

    assert "from fitmas.legacy.core import orm" in source
    assert "from fitmas import schema" not in source
    assert "import fitmas.schema" not in source
