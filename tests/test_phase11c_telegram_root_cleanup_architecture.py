from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_TELEGRAM_MODULES = {
    "telegram_api.py": "fitmas.telegram_api",
    "telegram_bot.py": "fitmas.telegram_bot",
    "telegram_channel.py": "fitmas.telegram_channel",
    "telegram_commands.py": "fitmas.telegram_commands",
    "telegram_debounce.py": "fitmas.telegram_debounce",
    "telegram_onboarding.py": "fitmas.telegram_onboarding",
    "telegram_shared.py": "fitmas.telegram_shared",
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


def test_11c_telegram_modules_live_under_app_package_only() -> None:
    expected_targets = {
        SRC / "app" / "telegram" / "api.py",
        SRC / "app" / "telegram" / "bot.py",
        SRC / "app" / "telegram" / "channel.py",
        SRC / "app" / "telegram" / "commands.py",
        SRC / "app" / "telegram" / "debounce.py",
        SRC / "app" / "telegram" / "onboarding.py",
        SRC / "app" / "telegram" / "shared.py",
    }

    assert all(path.exists() for path in expected_targets)
    assert [filename for filename in ROOT_TELEGRAM_MODULES if (SRC / filename).exists()] == []


def test_11c_no_python_imports_use_root_telegram_modules() -> None:
    forbidden = set(ROOT_TELEGRAM_MODULES.values())
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


def test_11c_scripts_launch_new_telegram_bot_module() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "scripts").iterdir()):
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if "python -m fitmas.telegram_bot" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
