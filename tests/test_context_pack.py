from fitmas.decision.context_pack import (
    ActiveThreadContext,
    CoachProfileContext,
    ConversationContextPack,
    ExecutionReality,
    MemoryContext,
    PlanningContext,
    TemporalContext,
    ToolBudget,
    TurnScope,
    build_conversation_context_pack,
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


def test_build_conversation_context_pack_from_summaries() -> None:
    pack = build_conversation_context_pack(
        route="conversation_plan_lookup",
        intent="plan_lookup",
        capability="read_only",
        time_context={"today": "2026-05-08"},
        temporal_summary="demain = 2026-05-09",
        timeline_summary="- Samedi: Footing 40 min",
        execution_summary="Hier repos tenu",
        selected_facts=("objectif 10 km",),
        working_facts=("tension tibias legere",),
        execution_facts=("repos tenu hier",),
        conversation_frame=("question plan demain",),
        history_messages=({"role": "user", "text": "J'ai quoi demain ?"},),
        coach_summary="Style direct",
        allowed_tools=("get_plan_window",),
        tool_choice="auto",
    )

    assert pack.turn_scope.route == "conversation_plan_lookup"
    assert pack.temporal.time_context == {"today": "2026-05-08"}
    assert pack.planning.timeline_summary == "- Samedi: Footing 40 min"
    assert pack.memory.durable_profile == ("objectif 10 km",)
    assert pack.memory.working_memory == ("tension tibias legere",)
    assert pack.active_thread.history_messages == ({"role": "user", "text": "J'ai quoi demain ?"},)
    assert pack.tool_budget.allowed_tools == ("get_plan_window",)
