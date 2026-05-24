from pathlib import Path


FORBIDDEN = (
    "fitmas.decision",
    "fitmas.domain",
    "fitmas.llm",
    "fitmas.skills",
    "fitmas.tools",
    "fitmas.app",
)


def test_runtime_v0_does_not_import_existing_runtime_layers():
    root = Path("backend/src/fitmas/runtime_v0")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path}: {forbidden}")
    assert offenders == []


def test_runtime_v0_core_stays_under_v0_budget():
    root = Path("backend/src/fitmas/runtime_v0")
    loc = sum(
        len(path.read_text().splitlines())
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert loc <= 2500
