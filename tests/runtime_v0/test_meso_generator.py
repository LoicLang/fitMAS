from __future__ import annotations

from datetime import date

import pytest

from fitmas.runtime_v0.meso.generator import EMIT_WEEK_TOOL, _build_week
from fitmas.runtime_v0.meso.model import (
    ContextPack,
    PlannedWeek,
    TypedConstraint,
    WeekActuals,
    derive_continuity_target,
)
from fitmas.runtime_v0.prompts.week_generation import (
    GENERATION_SYSTEM,
    render_generation_prompt,
)

MONDAY = date(2026, 6, 8)


def _pack(constraints=()):
    actuals = WeekActuals(total_load=300.0, key_type="threshold")
    return ContextPack(
        target=derive_continuity_target(actuals),
        last_week_actuals=actuals,
        constraints=constraints,
        signals=(),
    )


def test_generation_system_mentions_emit_tool():
    assert "emit_week" in GENERATION_SYSTEM


def test_render_prompt_includes_target_and_constraint():
    pack = _pack((TypedConstraint(severity="moderate", restricts=("intensity",), active=True),))
    text = render_generation_prompt(pack, MONDAY, "continuity")
    assert "threshold" in text          # prescribed key type
    assert "300.0" in text and "330.0" in text  # load band
    assert "2026-06-08" in text         # week start
    assert "intensity" in text          # active constraint surfaced


def test_build_week_parses_typed_sessions():
    week = _build_week(
        [
            {"date": "2026-06-09", "type": "threshold", "duration_min": 60, "intensity": "hard", "detail": "3x8"},
            {"date": "2026-06-13", "type": "easy_run", "duration_min": 40, "intensity": "easy"},
        ]
    )
    assert isinstance(week, PlannedWeek)
    assert week.week_load == 160.0  # 120 + 40
    assert week.sessions[0].type == "threshold"
    assert week.sessions[0].detail == "3x8"


def test_build_week_rejects_bad_type():
    with pytest.raises(ValueError):
        _build_week([{"date": "2026-06-09", "type": "sprint", "duration_min": 30, "intensity": "hard"}])


def test_build_week_rejects_bad_intensity():
    with pytest.raises(ValueError):
        _build_week([{"date": "2026-06-09", "type": "easy_run", "duration_min": 30, "intensity": "brutal"}])


def test_emit_week_tool_shape():
    assert EMIT_WEEK_TOOL.name == "emit_week"
    assert "sessions" in EMIT_WEEK_TOOL.parameters["properties"]
