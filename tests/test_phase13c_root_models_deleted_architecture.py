from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = [
    ROOT / "backend" / "src",
    ROOT / "tests",
    ROOT / "scripts",
]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return files


def test_13c_root_models_file_is_deleted() -> None:
    assert not (SRC / "models.py").exists()


def test_13c_no_code_imports_root_fitmas_models() -> None:
    forbidden = [
        "from fitmas." + "models import",
        "import fitmas." + "models",
        "from fitmas import " + "models",
    ]
    offenders: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in forbidden):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
