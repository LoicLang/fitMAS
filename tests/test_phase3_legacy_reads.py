from __future__ import annotations

from pathlib import Path


def test_app_read_models_do_not_load_legacy_week_plan_runtime_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/api_app.py",
        root / "backend/src/fitmas/api_stats.py",
        root / "backend/src/fitmas/performance_overview.py",
    ]
    forbidden = (
        "repo.get_active_plan",
        "repo.to_pydantic_plan",
        "WeeklyPlan",
        "week_plan",
    )

    offenders: list[str] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []
