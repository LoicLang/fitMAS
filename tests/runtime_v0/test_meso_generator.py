from __future__ import annotations

from datetime import date

import pytest

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.meso.generator import EMIT_WEEK_TOOL, _build_week, generate_week
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


def _emit(sessions):
    return LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": sessions}),))


# A healthy build week for band (300, 330): key threshold Tue + easy + easy + long.
# load = 100 + 60 + 50 + 105 = 315 (in band); Tue/Sun stress not adjacent.
_GOOD_WEEK = [
    {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},   # 100
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},     # 60
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},     # 50
    {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"}, # 105
]
_LOW_WEEK = [{"date": "2026-06-09", "type": "easy_run", "duration_min": 30, "intensity": "easy"}]


def test_generate_week_passes_first_try():
    llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.source == "llm"
    assert proposal.attempts == 1
    assert proposal.verdict.ok
    assert proposal.verdict.requires_pending is True


def test_generate_week_retries_then_passes():
    llm = FakeLLMClient([_emit(_LOW_WEEK), _emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.source == "llm"
    assert proposal.attempts == 2
    # the 2nd request carried the verifier violations from attempt 1
    second_messages = llm.requests[1]["messages"]
    assert any("load_drop" in m.get("content", "") for m in second_messages)


def test_generate_week_repairs_prose():
    llm = FakeLLMClient([LLMResponse(text="voici ta semaine ..."), _emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.attempts == 2
    second_messages = llm.requests[1]["messages"]
    assert any("emit_week" in m.get("content", "") for m in second_messages)
