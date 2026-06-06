from __future__ import annotations

from datetime import date

from fitmas.runtime_v0.meso.model import (
    ContextPack,
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
