from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def test_phase8b_does_not_enable_cutover_flags_by_default() -> None:
    sources = [
        SRC / "decision" / "conversation_pipeline.py",
        SRC / "skills" / "heartbeat" / "runtime_adapter.py",
        SRC / "app" / "telegram" / "scheduler.py",
    ]
    forbidden = (
        'os.environ["FITMAS_PLANNING_RUNTIME_CUTOVER"] = "1"',
        'os.environ["FITMAS_HEARTBEAT_RUNTIME_CUTOVER"] = "1"',
        'os.environ["FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE"] = "1"',
    )

    offenders: list[str] = []
    for path in sources:
        source = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.relative_to(SRC)}: {token}" for token in forbidden if token in source)

    assert offenders == []


def test_phase8b_decision_package_stays_free_of_legacy_adapters() -> None:
    decision_dir = SRC / "decision"
    offenders: list[str] = []

    for path in sorted(decision_dir.glob("*.py")):
        if path.name in {
            "command_application.py",
            "conversation_pipeline.py",
            "readonly_reply.py",
            "understanding_runtime.py",
            "coach_decision_runtime.py",
        }:
            continue
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy" in source or "conversation_pipeline" in source:
            offenders.append(path.name)

    assert offenders == []
