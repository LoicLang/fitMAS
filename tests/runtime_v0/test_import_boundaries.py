from pathlib import Path


FORBIDDEN = (
    "fitmas.decision",
    "fitmas.domain",
    "fitmas.llm",
    "fitmas.skills",
    "fitmas.tools",
    "fitmas.app",
)

ROOT = Path("backend/src/fitmas/runtime_v0")


def _core_files() -> list[Path]:
    """V0 core files only.

    `adapters/` is the legacy bridge: it MAY import the existing product (core
    ORM today, domain writers later) and does not count against the core budget.
    The core is everything else and stays isolated + offline-testable.
    """
    return [
        path
        for path in ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and "adapters" not in path.parts
        and " 2" not in path.name  # ignore macOS/sync duplicate copies ("foo 2.py")
    ]


def test_runtime_v0_core_does_not_import_existing_runtime_layers():
    offenders = []
    for path in _core_files():
        text = path.read_text()
        for forbidden in FORBIDDEN:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path}: {forbidden}")
    assert offenders == []


def test_runtime_v0_core_does_not_import_adapters():
    # Dependency points one way: adapters -> core, never core -> adapters. The
    # core consumes an isolated v0_* DB; it must never reach into the bridge.
    offenders = []
    for path in _core_files():
        text = path.read_text()
        if (
            "runtime_v0.adapters" in text
            or "from .adapters" in text
            or "from ..adapters" in text
        ):
            offenders.append(str(path))
    assert offenders == []


def test_runtime_v0_core_stays_under_v0_budget():
    # Cap raised 3200 -> 3700 (5 juin 2026): Meso sport engine (meso/), fact
    # resolution, and the fact-rider (note a durable fact + act in one turn).
    # 3700 -> 3720 (5 juin 2026): Slice 2.0 context-pack (ContextPack +
    # build_context_pack + actuals_from_week, voie b forward-only).
    # 3720 -> 3960 (6 juin 2026): Slice 2.1 generator (generator.py, week_generation
    # prompt, constraint-aware relaxation).
    # 3960 -> 3970 (7 juin 2026): Slice 3a week_proposal type + WeekProposalDraft
    # + _week_proposal_from_dict in proposals.py.
    # Deliberate, planned capability growth, not creep. Bump per real growth
    # only; keep watching the ratchet (healthy target stays 2500).
    loc = sum(len(path.read_text().splitlines()) for path in _core_files())
    assert loc <= 3970
