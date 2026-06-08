from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "backend" / "src" / "fitmas" / "decision" / "conversation_pipeline.py"

ALLOWED_IMPORT_PREFIXES = {
    "__future__",
    "sqlalchemy.orm",
    "fitmas",
    "fitmas.repository",
    "fitmas.legacy.decision",
    "fitmas.legacy.decision.conversation_contract",
    "fitmas.models",
}

FORBIDDEN_RUNTIME_TOKENS = {
    "fitmas.legacy.llm",
    "claim_guard",
    "DecisionReplyComposer",
    "ConversationTurnOutcome",
    "reply_and_record_turn",
    "compose_canonical",
    "handle_canonical_planning",
    "apply_pending_resolution",
    "build_conversation_context",
    "build_coach_state_bundle",
    "extract_calibration_resolution",
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


def test_10w_conversation_pipeline_is_public_adapter_only() -> None:
    assert _function_names(PIPELINE) == {"run_conversation_turn", "_run_conversation_turn_impl"}


def test_10w_conversation_pipeline_has_only_adapter_imports() -> None:
    offenders = [
        module
        for module in _imports(PIPELINE)
        if not any(module == allowed or module.startswith(f"{allowed}.") for allowed in ALLOWED_IMPORT_PREFIXES)
    ]

    assert offenders == []


def test_10w_conversation_pipeline_has_no_runtime_decision_tokens() -> None:
    source = _source(PIPELINE)

    assert [token for token in FORBIDDEN_RUNTIME_TOKENS if token in source] == []


def test_10w_conversation_pipeline_stays_tiny() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 90
