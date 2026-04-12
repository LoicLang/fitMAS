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


def test_conversation_runtime_does_not_load_legacy_week_plan_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/conversation_pipeline.py",
        root / "backend/src/fitmas/conversation_contract.py",
    ]
    forbidden = (
        "pydantic_plan",
        "repo.get_active_plan",
        "repo.to_pydantic_plan",
        "week_plan=state.",
    )

    offenders: list[str] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []


def test_heartbeat_runtime_does_not_load_legacy_week_plan_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/skills/heartbeat/heartbeat.py",
    ]
    forbidden = (
        "repo.get_active_plan",
        "repo.to_pydantic_plan",
        "week_plan=",
    )

    offenders: list[str] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []


def test_legacy_week_endpoint_is_marked_template_compat() -> None:
    root = Path(__file__).resolve().parents[1]
    models = (root / "backend/src/fitmas/models.py").read_text()
    assert 'runtime_role: str = "template_compat"' in models


def test_telegram_plan_command_uses_dated_timeline_not_legacy_week() -> None:
    root = Path(__file__).resolve().parents[1]
    commands = (root / "backend/src/fitmas/telegram_commands.py").read_text()
    assert 'api_get("/api/v0/week")' not in commands
    assert 'api_get("/api/v0/timeline' in commands
