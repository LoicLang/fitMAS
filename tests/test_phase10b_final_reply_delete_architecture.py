from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
TESTS = ROOT / "tests"
SCRIPTS = ROOT / "scripts"
CENSUS = ROOT / "docs" / "ROOT-MODULE-CENSUS.md"


def _python_like_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".py" or (root == SCRIPTS and path.suffix == ""):
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


def _census_row_files() -> set[str]:
    row_files: set[str] = set()
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row_files.add(cells[0].strip("`"))
    return row_files


def test_10b_deletes_root_final_reply_backend() -> None:
    assert not (SRC / "final_reply.py").exists()


def test_10b_deletes_forwarding_conversation_reply_adapter() -> None:
    assert not (SRC / "legacy" / "conversation_reply_adapter.py").exists()


def test_10b_no_imports_target_root_final_reply() -> None:
    offenders: list[str] = []
    forbidden = {"fitmas.final_reply", "fitmas.final_reply.final_reply"}
    for path in _python_like_files(SRC, TESTS, SCRIPTS):
        hit = _imports(path) & forbidden
        if hit:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert offenders == []


def test_10b_root_census_drops_final_reply_row() -> None:
    assert "final_reply.py" not in _census_row_files()


def test_10b_reply_backend_modules_stay_bounded() -> None:
    checked = [
        SRC / "llm" / "reply_backend.py",
        SRC / "llm" / "reply_verifiers.py",
        SRC / "skills" / "heartbeat" / "reply_composer.py",
    ]
    offenders: list[str] = []
    for path in checked:
        if not path.exists():
            offenders.append(f"{path.relative_to(ROOT)}: missing")
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > 550:
            offenders.append(f"{path.relative_to(ROOT)}: {line_count} lines")
    assert offenders == []
