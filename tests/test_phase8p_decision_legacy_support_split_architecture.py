from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
LLM = SRC / "llm"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8p_support_modules_exist() -> None:
    assert (LLM / "legacy_summaries.py").exists()
    assert (LLM / "legacy_onboarding.py").exists()
    assert (LLM / "legacy_fact_memory.py").exists()


def test_8p_decision_legacy_no_longer_imports_support_domains_directly() -> None:
    imports = _imports("llm/decision_legacy.py")
    forbidden = {
        "fitmas.fact_memory",
        "fitmas.knowledge",
        "fitmas.onboarding_contract",
        "fitmas.time_context",
    }
    assert not forbidden.intersection(imports)


def test_8p_public_compat_wrappers_remain_in_decision_legacy() -> None:
    source = _source("llm/decision_legacy.py")
    for name in (
        "def make_plan_summary(",
        "def make_timeline_summary(",
        "def preview_coach_voice(",
        "def formulate_onboarding_recap(",
        "def formulate_week_plan(",
        "def extract_facts(",
        "def select_prompt_facts(",
    ):
        assert name in source


def test_8p_decision_legacy_keeps_decide_but_not_large_support_prompts() -> None:
    source = _source("llm/decision_legacy.py")

    assert "def decide(" in source
    assert "Tu dois enrichir un squelette de semaine multisport" not in source
    assert "Analyse cet echange et decide s'il faut memoriser" not in source
    assert source.count("\n") < 760


def test_8p_smoke_wrapper_is_deterministic_only() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-decision-legacy-support-split").read_text(encoding="utf-8")

    assert "tests/test_phase8p_decision_legacy_support_split_architecture.py" in source
    assert "tests/test_llm_legacy_summaries.py" in source
    assert "tests/test_llm_legacy_onboarding.py" in source
    assert "tests/test_llm_legacy_fact_memory.py" in source
    assert "smoke-decision-runtime-coachdecision-artifact" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
