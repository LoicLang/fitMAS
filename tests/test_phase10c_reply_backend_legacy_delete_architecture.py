from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
TESTS = ROOT / "tests"
SCRIPTS = ROOT / "scripts"


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


def test_10c_deletes_legacy_final_reply_backend() -> None:
    assert not (SRC / "legacy" / "final_reply_backend.py").exists()


def test_10c_no_runtime_imports_legacy_final_reply_backend() -> None:
    offenders: list[str] = []
    forbidden = {
        "fitmas.legacy.final_reply_backend",
        "fitmas.legacy.final_reply_backend.LegacyFinalReplyBackend",
    }
    for path in _python_like_files(SRC, TESTS, SCRIPTS):
        hit = _imports(path) & forbidden
        if hit:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert offenders == []


def test_10c_llm_reply_backend_implements_decision_reply_protocol() -> None:
    target = SRC / "llm" / "reply_decision_backend.py"
    assert target.exists()
    source = target.read_text(encoding="utf-8")

    assert "class LLMReplyBackend" in source
    assert "LegacyFinalReplyBackend" not in source
    assert "def compose(self, request: ReplyRequest)" in source
