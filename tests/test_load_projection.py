from __future__ import annotations

from fitmas.load_projection import build_load_forecast


def test_load_forecast_returns_four_weeks_and_deload() -> None:
    forecast = build_load_forecast(
        current_ctl=58.0,
        current_target_tss=420.0,
        current_cycle_week=1,
        weeks=4,
        planning_mode="increase_load",
    )

    assert len(forecast) == 4
    assert forecast[-1].is_deload is True
    assert forecast[0].target_tss > 400
    assert forecast[-1].target_tss < forecast[-2].target_tss


def test_load_forecast_projects_ctl_forward() -> None:
    forecast = build_load_forecast(
        current_ctl=40.0,
        current_target_tss=350.0,
        current_cycle_week=2,
        weeks=2,
        planning_mode="maintain_load",
    )

    assert forecast[0].projected_ctl > 40.0
    assert forecast[1].projected_ctl > 0
