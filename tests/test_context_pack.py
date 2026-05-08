from fitmas.context_pack import (
    ActiveThreadContext,
    CoachProfileContext,
    ConversationContextPack,
    ExecutionReality,
    MemoryContext,
    PlanningContext,
    TemporalContext,
    ToolBudget,
    TurnScope,
)


def test_context_pack_exposes_memory_families() -> None:
    pack = ConversationContextPack(
        turn_scope=TurnScope(route="conversation_plan_lookup", intent="plan_lookup", capability="read_only"),
        temporal=TemporalContext(time_context={"today": "2026-05-08"}, temporal_summary="demain = 2026-05-09"),
        planning=PlanningContext(timeline_summary="- Samedi: Footing 40 min"),
        execution=ExecutionReality(execution_summary="Hier repos tenu"),
        memory=MemoryContext(
            durable_profile=("objectif 10 km",),
            working_memory=("tension tibias legere",),
            execution_reality=("repos tenu hier",),
            conversation_frame=("question plan demain",),
        ),
        active_thread=ActiveThreadContext(history_messages=()),
        coach_profile=CoachProfileContext(summary="Style direct"),
        tool_budget=ToolBudget(allowed_tools=("get_plan_window",), tool_choice="auto"),
        grounding=None,
    )

    assert pack.memory.family_names() == (
        "durable_profile",
        "working_memory",
        "execution_reality",
        "conversation_frame",
    )
    assert pack.truth_block_names() == (
        "temporal",
        "planning",
        "execution",
        "memory",
        "active_thread",
        "coach_profile",
        "tool_budget",
    )


def test_tool_budget_defaults_to_no_tools() -> None:
    budget = ToolBudget()

    assert budget.allowed_tools == ()
    assert budget.tool_choice is None
