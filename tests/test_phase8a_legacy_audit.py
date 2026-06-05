from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _imports(path: Path) -> list[ast.Import | ast.ImportFrom]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]


def _relative(path: Path) -> str:
    return str(path.relative_to(SRC))


def _legacy_final_reply_callers() -> list[Path]:
    callers: list[Path] = []

    for path in sorted(SRC.rglob("*.py")):
        if path.name == "final_reply.py":
            continue
        for node in _imports(path):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fitmas" and any(alias.name == "final_reply" for alias in node.names):
                    callers.append(path)
                    break
                if node.module == "fitmas.final_reply":
                    callers.append(path)
                    break
            elif isinstance(node, ast.Import):
                if any(alias.name == "fitmas.final_reply" for alias in node.names):
                    callers.append(path)
                    break

    return callers


def test_phase8a_no_legacy_final_reply_callers() -> None:
    callers = [_relative(path) for path in _legacy_final_reply_callers()]

    assert callers == []
