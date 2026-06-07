"""Coach-callable `propose_week` tool — the engine entry point in the runtime (Slice 3a).

The coach declares a seed (last week's load + key type, read from real recent training);
this builds a ContextPack from the snapshot and runs the Meso generator with the
injected generation_llm (bigger token budget than the chat loop). It only PROPOSES:
the returned week_proposal carries the week as answer_facts and triggers no write
(the policy routes it to answer_only). Commit/store/chaining is Slice 3b.
"""
from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.context import constraints_from_snapshot
from fitmas.runtime_v0.meso.generator import generate_week
from fitmas.runtime_v0.meso.model import ContextPack, WeekActuals, derive_continuity_target
from fitmas.runtime_v0.proposals import ActionProposal, WeekProposalDraft
from fitmas.runtime_v0.tools_proposal import _record, _trace
from fitmas.runtime_v0.tools_read import ToolContext


def _next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def propose_week(
    ctx: ToolContext,
    last_week_load: float,
    key_type: str,
    phase: str = "build",
) -> ActionProposal:
    if ctx.generation_llm is None:
        # Fail loud on misconfiguration rather than crashing deep in generate_week
        # (a None client would AttributeError before the template fallback).
        raise ValueError("propose_week requires generation_llm; inject it via RuntimeDeps")
    snapshot = ctx.snapshot
    # Forward chaining: a committed prior week is the seed of record; the
    # LLM-declared seed is the cold-start fallback (no committed week yet).
    actuals = snapshot.last_planned_week or WeekActuals(
        total_load=float(last_week_load), key_type=key_type
    )
    target = derive_continuity_target(actuals, phase)
    pack = ContextPack(
        target=target,
        last_week_actuals=actuals,
        constraints=constraints_from_snapshot(snapshot),
        signals=(),
    )
    week_start = _next_monday(snapshot.today)
    result = generate_week(ctx.generation_llm, pack, week_start)
    sessions = tuple(
        {
            "date": session.date.isoformat(),
            "type": session.type,
            "duration_min": session.duration_min,
            "intensity": session.intensity,
            "detail": session.detail,
        }
        for session in result.week.sessions
    )
    draft = WeekProposalDraft(
        week_start=week_start.isoformat(),
        source=result.source,
        week_load=result.week.week_load,
        band=target.load_band,
        key_type=actuals.key_type,
        sessions=sessions,
    )
    facts = (
        f"semaine proposée du {week_start.isoformat()} — charge {result.week.week_load} "
        f"(cible {target.load_band[0]}-{target.load_band[1]}, clé {actuals.key_type})",
    ) + tuple(
        f"{s['date']} {s['type']} {s['duration_min']}min {s['intensity']}" for s in sessions
    )
    _record(ctx, "propose_week", True)
    return ActionProposal(
        type="week_proposal",
        confidence=0.8,
        user_intent_summary="week proposal",
        evidence=facts,
        answer_facts=facts,
        week_proposal=draft,
        tool_trace=_trace(ctx),
    )
