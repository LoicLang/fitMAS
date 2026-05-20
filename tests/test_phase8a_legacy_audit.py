from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
AUDIT_DOC = ROOT / "docs" / "DECISION-RUNTIME-LEGACY-KILL-LIST.md"


def _doc_text() -> str:
    assert AUDIT_DOC.exists(), "Phase 8A must publish the legacy kill list doc"
    return AUDIT_DOC.read_text(encoding="utf-8")


def _imports(path: Path) -> list[ast.Import | ast.ImportFrom]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]


def _relative(path: Path) -> str:
    return str(path.relative_to(SRC))


def _legacy_llm_contract_importers() -> list[Path]:
    importers: list[Path] = []
    legacy_contracts = {"CoachDecision", "MutationDecision"}

    for path in sorted(SRC.rglob("*.py")):
        for node in _imports(path):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "fitmas.llm":
                continue
            if any(alias.name in legacy_contracts for alias in node.names):
                importers.append(path)
                break

    return importers


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


def test_phase8a_legacy_kill_list_doc_exists_with_front_matter() -> None:
    source = _doc_text()

    assert source.startswith("---\n")
    assert "summary:" in source
    assert "read_when:" in source
    assert "# Decision Runtime Legacy Kill List" in source


def test_phase8a_doc_lists_all_legacy_llm_contract_importers() -> None:
    doc = _doc_text()
    importers = [_relative(path) for path in _legacy_llm_contract_importers()]
    allowed_importers: set[str] = set()

    assert sorted(set(importers) - allowed_importers) == []
    assert [path for path in importers if path not in doc] == []


def test_phase8a_doc_lists_all_legacy_final_reply_callers() -> None:
    doc = _doc_text()
    callers = [_relative(path) for path in _legacy_final_reply_callers()]

    assert callers
    assert [path for path in callers if path not in doc] == []


def test_phase8a_doc_tracks_cutover_flags_and_legacy_tools() -> None:
    doc = _doc_text()
    required_tokens = {
        "FITMAS_PLANNING_RUNTIME_CUTOVER",
        "FITMAS_HEARTBEAT_RUNTIME_CUTOVER",
        "FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE",
        "suggest_replan_candidates",
        "propose_replan",
        "draft_move_session",
        "draft_swap_sessions",
        "draft_replace_session",
        "draft_lighten_day",
        "draft_create_session",
    }

    assert sorted(token for token in required_tokens if token not in doc) == []


def test_phase8a_doc_keeps_audit_separate_from_deletion() -> None:
    doc = _doc_text()

    assert "Phase 8A ne supprime pas" in doc
    assert "Phase 8B" in doc
    assert "Phase 8C" in doc
