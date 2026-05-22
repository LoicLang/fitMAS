from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _backend_python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_12l_coach_messages_are_owned_by_telegram_delivery() -> None:
    assert not (SRC / "coach_messages.py").exists()
    assert (SRC / "app/telegram/delivery.py").exists()


def test_12l_no_backend_imports_root_coach_messages() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        imports = _imports(path)
        if "fitmas.coach_messages" in imports:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
