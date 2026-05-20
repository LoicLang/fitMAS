from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text()


def _python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend((ROOT / root).rglob("*.py"))
    return sorted(files)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(SRC))
    except ValueError:
        return str(path.relative_to(ROOT))


def test_9v_llm_package_is_a_thin_package_marker() -> None:
    source = _source("llm/__init__.py")

    assert "decision_legacy" not in source
    assert "CoachDecision" not in source
    assert "MutationDecision" not in source
    assert "parse_coach_decision_payload" not in source
    assert "def decide" not in source
    assert "__getattr__" not in source
    assert len(source.splitlines()) <= 12


def test_9v_legacy_contracts_are_not_reexported_from_llm_package() -> None:
    assert not (SRC / "llm" / "legacy_models.py").exists()


def test_9v_tests_do_not_import_legacy_contracts_from_fitmas_llm() -> None:
    offenders: list[str] = []
    contract_names = {
        "AcceptPendingResolution",
        "AvailabilityConstraintAction",
        "CoachDecision",
        "ExecutionUpdateAction",
        "HealthSignalAction",
        "IgnorePendingResolution",
        "MemoryAction",
        "ModifyPendingResolution",
        "MutationDecision",
        "NeedsClarificationPendingResolution",
        "PendingResolution",
        "PreferenceSignalAction",
        "RejectPendingResolution",
    }
    allowed_broad_import_tests = {"tests/test_llm_package_compat.py"}
    for path in _python_files("tests"):
        relative = _relative(path)
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fitmas.llm":
                imported = {alias.name for alias in node.names}
                if imported & contract_names:
                    offenders.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fitmas.llm" and relative not in allowed_broad_import_tests:
                        offenders.append(f"{relative}:{node.lineno}")

    assert offenders == []


def test_9w_safe_outcomes_use_canonical_modes() -> None:
    forbidden = (
        "legacy_provider_denied",
        "planning_runtime_unhandled",
        "no_change_safe_fallback",
    )
    offenders: list[str] = []
    for path in _python_files("backend/src/fitmas"):
        relative = _relative(path)
        if relative.startswith("docs/"):
            continue
        source = path.read_text()
        for token in forbidden:
            if token in source:
                offenders.append(f"{relative}:{token}")

    assert offenders == []


def test_9w_canonical_safe_modes_are_declared() -> None:
    combined = "\n".join(path.read_text() for path in _python_files("backend/src/fitmas"))

    assert "canonical_provider_clarification" in combined
    assert "canonical_planning_blocked" in combined
    assert "canonical_no_action_safe_reply" in combined
