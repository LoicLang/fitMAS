from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def test_12x_production_source_does_not_import_root_repository_facade() -> None:
    offenders: list[str] = []
    forbidden_markers = (
        "from fitmas import " + "repository",
        "import fitmas." + "repository",
    )
    for path in SRC.rglob("*.py"):
        if path == SRC / "repository.py":
            continue
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in forbidden_markers):
            offenders.append(str(path.relative_to(SRC)))

    assert sorted(set(offenders)) == []
