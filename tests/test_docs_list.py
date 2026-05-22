from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_docs_list_module():
    spec = importlib.util.spec_from_file_location("fitmas_docs_list", ROOT / "scripts" / "docs_list.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_docs_list_default_excludes_archive_and_superpowers_history() -> None:
    docs_list = _load_docs_list_module()

    files = [path.relative_to(docs_list.DOCS_DIR).as_posix() for path in docs_list.walk_markdown_files(docs_list.DOCS_DIR)]

    assert "README.md" in files
    assert not any(path.startswith("archive/") for path in files)
    assert not any(path.startswith("superpowers/") for path in files)


def test_docs_list_all_includes_archived_context_when_requested() -> None:
    docs_list = _load_docs_list_module()

    files = [
        path.relative_to(docs_list.DOCS_DIR).as_posix()
        for path in docs_list.walk_markdown_files(docs_list.DOCS_DIR, include_all=True)
    ]

    assert any(path.startswith("archive/") for path in files)
    assert any(path.startswith("archive/refactor-2026-05-21/") for path in files)
    assert not any(path.startswith("superpowers/") for path in files)
