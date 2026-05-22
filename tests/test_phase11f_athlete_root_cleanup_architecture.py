from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_ATHLETE_MODULES = {
    "athlete_profile.py": "fitmas.athlete_profile",
    "athlete_zones.py": "fitmas.athlete_zones",
    "fitness_snapshot.py": "fitmas.fitness_snapshot",
    "load_projection.py": "fitmas.load_projection",
    "performance_overview.py": "fitmas.performance_overview",
    "performance_stats.py": "fitmas.performance_stats",
    "readiness.py": "fitmas.readiness",
    "strength_engine.py": "fitmas.strength_engine",
    "strength_exercise_bank.py": "fitmas.strength_exercise_bank",
    "strength_signals.py": "fitmas.strength_signals",
    "threshold_estimation.py": "fitmas.threshold_estimation",
    "training_load.py": "fitmas.training_load",
}

TARGET_ATHLETE_MODULES = {
    "profile.py",
    "zones.py",
    "fitness_snapshot.py",
    "load_projection.py",
    "performance_overview.py",
    "performance_stats.py",
    "readiness.py",
    "strength_engine.py",
    "strength_exercise_bank.py",
    "strength_signals.py",
    "threshold_estimation.py",
    "training_load.py",
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


def test_11f_athlete_modules_live_under_domain_package_only() -> None:
    target_dir = SRC / "domain" / "athlete"

    assert all((target_dir / filename).exists() for filename in TARGET_ATHLETE_MODULES)
    assert [filename for filename in ROOT_ATHLETE_MODULES if (SRC / filename).exists()] == []


def test_11f_no_python_imports_use_root_athlete_modules() -> None:
    forbidden = set(ROOT_ATHLETE_MODULES.values())
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
