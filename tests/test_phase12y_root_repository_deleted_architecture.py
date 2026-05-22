from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def test_12y_root_repository_module_is_deleted() -> None:
    assert not (SRC / "repository.py").exists()


def test_12y_no_active_code_or_tests_import_root_repository() -> None:
    offenders: list[str] = []
    forbidden_markers = (
        "from fitmas import " + "repository",
        "import fitmas." + "repository",
        "from fitmas." + "repository import",
    )
    for base in (ROOT / "backend" / "src" / "fitmas", ROOT / "tests", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            if path.name == "test_phase12y_root_repository_deleted_architecture.py":
                continue
            source = path.read_text(encoding="utf-8")
            if any(marker in source for marker in forbidden_markers):
                offenders.append(str(path.relative_to(ROOT)))

    assert sorted(set(offenders)) == []
