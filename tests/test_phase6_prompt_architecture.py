from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "backend" / "src" / "fitmas" / "llm" / "prompts"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_prompt_package_has_canonical_prompt_modules() -> None:
    modules = {path.name for path in PROMPTS.glob("*.py")}

    assert {"base.py", "contracts.py", "understanding.py", "reviewer.py", "reply.py", "__init__.py"}.issubset(modules)


def test_new_prompt_modules_do_not_import_runtime_or_writers() -> None:
    forbidden_exact = {
        "fitmas.conversation_pipeline",
        "fitmas.db",
        "fitmas.models",
        "fitmas.plan_mutation_service",
        "fitmas.memory_mutation_service",
        "fitmas.domain.execution.mutation_service",
        "fitmas.legacy",
    }
    offenders: list[str] = []
    for path in sorted(PROMPTS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for module in _imports(path):
            if module in forbidden_exact or module.startswith("sqlalchemy"):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_understanding_prompt_source_has_no_legacy_output_tokens() -> None:
    source = (PROMPTS / "understanding.py").read_text(encoding="utf-8")
    forbidden = ("fitmas_message", "MutationDecision", "PlanPatch", "reply_text", "final_reply")

    assert [token for token in forbidden if token in source] == []


def test_reviewer_prompt_source_does_not_create_patch_or_user_text() -> None:
    source = (PROMPTS / "reviewer.py").read_text(encoding="utf-8")
    forbidden = ("fitmas_message", "coach_message", "reply_text", "commands")

    assert [token for token in forbidden if token in source] == []
