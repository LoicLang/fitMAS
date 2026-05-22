from __future__ import annotations

from pathlib import Path


def test_app_read_models_do_not_load_legacy_week_plan_runtime_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/app/api/routes_app.py",
        root / "backend/src/fitmas/app/api/routes_stats.py",
        root / "backend/src/fitmas/domain/athlete/performance_overview.py",
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
        root / "backend/src/fitmas/decision/conversation_pipeline.py",
        root / "backend/src/fitmas/decision/conversation_contract.py",
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


def test_week_endpoint_uses_scheduled_runtime_truth_before_template_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    api_read = (root / "backend/src/fitmas/app/api/routes_read.py").read_text()
    assert "repo.get_scheduled_sessions_between_dates" in api_read
    assert "_build_runtime_week_plan" in api_read
    assert 'runtime_role="scheduled_runtime"' in api_read


def test_telegram_plan_command_uses_dated_timeline_not_legacy_week() -> None:
    root = Path(__file__).resolve().parents[1]
    commands = (root / "backend/src/fitmas/app/telegram/commands.py").read_text()
    assert 'api_get("/api/v0/week")' not in commands
    assert 'api_get("/api/v0/timeline' in commands


def test_activity_import_runtime_does_not_load_legacy_week_plan_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/app/api/routes_activities.py",
        root / "backend/src/fitmas/integrations/strava.py",
    ]
    forbidden = (
        "repo.get_active_plan",
        "repo.to_pydantic_plan",
        "week_days",
        "mark_day_completed_for_user",
    )

    offenders: list[str] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []


def test_runtime_truth_modules_do_not_read_or_write_legacy_week_plan() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend/src/fitmas/domain/planning/session_actions.py",
        root / "backend/src/fitmas/domain/planning/mutation_executor.py",
        root / "backend/src/fitmas/domain/coaching/signals.py",
        root / "backend/src/fitmas/domain/execution/activities.py",
    ]
    forbidden = (
        "WeeklyPlan",
        "DayPlan",
        "get_active_plan",
        "get_day_plan",
        "get_current_week_day_plan_for_session",
        "repo.move_session(",
        "repo.set_change_notes",
        "repo.resync_plan_sessions",
        "repo.mark_day_completed",
    )

    offenders: list[str] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []
