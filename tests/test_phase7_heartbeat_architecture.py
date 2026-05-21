from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_app_telegram_scheduler_exists_without_root_compat_wrapper() -> None:
    target = SRC / "app" / "telegram" / "scheduler.py"
    wrapper = SRC / "telegram_scheduler.py"

    assert target.exists()
    assert not wrapper.exists()


def test_decision_package_imports_no_heartbeat_or_telegram_runtime() -> None:
    forbidden = {
        "fitmas.heartbeat",
        "fitmas.skills.heartbeat",
        "fitmas.telegram_scheduler",
        "fitmas.app.telegram",
        "fitmas.coach_messages",
    }
    offenders: list[str] = []

    for path in sorted(DECISION.glob("*.py")):
        for module in _imports(path):
            if module in forbidden or module.startswith("fitmas.skills.heartbeat."):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_heartbeat_runtime_adapter_has_no_delivery_or_persistence_side_effects() -> None:
    source = (SRC / "skills" / "heartbeat" / "runtime_adapter.py").read_text(encoding="utf-8")
    forbidden = ("send_message", "persist_draft", "persist_draft_for_owner", "SessionLocal", ".commit(", ".flush(")

    assert [token for token in forbidden if token in source] == []


def test_heartbeat_runtime_bridge_imports_are_explicitly_bounded() -> None:
    allowed = {
        SRC / "app" / "telegram" / "scheduler.py",
        SRC / "telegram_commands.py",
        SRC / "api_debug.py",
        SRC / "api_ops.py",
    }
    offenders: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        if "/skills/heartbeat/" in str(path):
            continue
        modules = _imports(path)
        if not any(module == "fitmas.skills.heartbeat" or module.startswith("fitmas.skills.heartbeat.") for module in modules):
            continue
        if path not in allowed:
            offenders.append(str(path.relative_to(SRC)))

    assert offenders == []
