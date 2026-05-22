from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_COACHING_MODULES = {
    "adaptation_log.py": "fitmas.adaptation_log",
    "calibration_needs.py": "fitmas.calibration_needs",
    "calibration_status.py": "fitmas.calibration_status",
    "coach_reading_digest.py": "fitmas.coach_reading_digest",
    "coach_voice.py": "fitmas.coach_voice",
    "generated_week_coherence.py": "fitmas.generated_week_coherence",
    "repo_conversation.py": "fitmas.repo_conversation",
    "week_context.py": "fitmas.week_context",
}

TARGET_COACHING_MODULES = {
    "adaptation_log.py",
    "calibration_needs.py",
    "calibration_status.py",
    "coach_reading_digest.py",
    "coach_voice.py",
    "generated_week_coherence.py",
    "repo_conversation.py",
    "week_context.py",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_11g_coaching_modules_live_under_domain_package_only() -> None:
    target_dir = SRC / "domain" / "coaching"

    assert all((target_dir / filename).exists() for filename in TARGET_COACHING_MODULES)
    assert [filename for filename in ROOT_COACHING_MODULES if (SRC / filename).exists()] == []


def test_11g_no_python_imports_use_root_coaching_modules() -> None:
    forbidden = set(ROOT_COACHING_MODULES.values())
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            matched = sorted(module for module in imports if module in forbidden)
            if matched:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(matched)}")

    assert offenders == []
