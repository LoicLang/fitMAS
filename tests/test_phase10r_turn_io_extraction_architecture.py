from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"
PIPELINE = SRC / "decision" / "conversation_pipeline.py"


PIPELINE_HELPERS_TO_REMOVE = {
    "_active_memory_payloads",
    "_client_message_key_lock",
    "_day_id_from_row",
    "_filter_legacy_extracted_facts",
    "_latest_agent_text",
    "_load_turn_state",
    "_obsolete_turn_outcome",
    "_persist_turn_memory_updates",
    "_reply_and_record_turn",
    "_reply_for_duplicate_client_message",
    "_turn_is_obsolete",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def test_10r_turn_io_modules_exist_under_decision() -> None:
    assert (DECISION / "turn_idempotency.py").exists()
    assert (DECISION / "turn_state.py").exists()
    assert (DECISION / "turn_persistence.py").exists()


def test_10r_conversation_pipeline_no_longer_defines_turn_io_helpers() -> None:
    pipeline_functions = _function_names(PIPELINE)

    assert PIPELINE_HELPERS_TO_REMOVE.isdisjoint(pipeline_functions)


def test_10r_conversation_pipeline_imports_turn_io_owners() -> None:
    imports = _imports(PIPELINE)

    assert "fitmas.legacy.decision.turn_idempotency" in imports
    assert "fitmas.legacy.decision.turn_state" in imports
    assert (DECISION / "turn_persistence.py").exists()


def test_10r_turn_io_owners_do_not_import_conversation_pipeline() -> None:
    offenders = []
    for path in (
        DECISION / "turn_idempotency.py",
        DECISION / "turn_state.py",
        DECISION / "turn_persistence.py",
    ):
        imports = _imports(path)
        if "fitmas.conversation_pipeline" in imports:
            offenders.append(path.name)

    assert offenders == []


def test_10r_conversation_pipeline_shrinks_below_turn_io_budget() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 1050
