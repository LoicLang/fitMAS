from pathlib import Path

from fitmas.context_pack import build_conversation_context_pack
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt
from fitmas.tools.routing import IntentCategory


SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "prompts"


def _render_bundle_snapshot(*, route: str, output_schema: str, bundle) -> str:
    trace = bundle.trace.as_dict() if bundle.trace else {}
    system = "\n\n--- SYSTEM PART ---\n\n".join(str(part.get("text") or "") for part in bundle.system)
    return "\n".join(
        (
            f"route: {route}",
            f"contract: {trace.get('prompt_contract') or 'none'}",
            f"tool_budget: {list(trace.get('tool_names') or ())}",
            f"truth_blocks: {list(trace.get('truth_block_names') or ())}",
            f"output_schema: {output_schema}",
            f"trace: {trace}",
            "",
            "## SYSTEM",
            system,
            "",
            "## USER",
            bundle.prompt,
            "",
        )
    )


def _conversation_plan_lookup_snapshot() -> str:
    policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    context_pack = build_conversation_context_pack(
        route="conversation_plan_lookup",
        intent="plan_lookup",
        capability="read_only",
        time_context={"today": "2026-05-08"},
        temporal_summary="References temporelles resolues: demain = 2026-05-09.",
        timeline_summary="- Samedi 9 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        selected_facts=(),
        execution_facts=("hier repos tenu",),
        conversation_frame=("question factuelle sur demain",),
        history_messages=(
            {"role": "assistant", "text": "Vendredi tu souffles, samedi footing Z2."},
            {"role": "user", "text": "Ok."},
        ),
        coach_summary="Objectif: construire 10 km regulier. Style: direct.",
        allowed_tools=("get_plan_window", "get_session_detail"),
        tool_choice="auto",
    )
    bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi 8 mai 2026.",
        profile_summary="Objectif: construire 10 km regulier. Style: direct.",
        timeline_summary="- Samedi 9 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="References temporelles resolues: demain = 2026-05-09.",
        activity_claim_summary="Claims recents: aucun claim non resolu.",
        signal_summary="",
        conversation_history=[
            {"role": "assistant", "text": "Vendredi tu souffles, samedi footing Z2."},
            {"role": "user", "text": "Ok."},
        ],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=[],
        context_pack=context_pack,
    )
    return _render_bundle_snapshot(
        route="conversation_plan_lookup",
        output_schema="CoachDecision",
        bundle=bundle,
    )


def _conversation_close_turn_snapshot() -> str:
    policy = select_conversation_prompt_policy(intent=IntentCategory.CLOSE_TURN)
    context_pack = build_conversation_context_pack(
        route="conversation_close_turn",
        intent="close_turn",
        capability="terminal_text",
        time_context={"today": "2026-05-08"},
        temporal_summary="References temporelles resolues: aujourd'hui = 2026-05-08.",
        timeline_summary="- Vendredi 8 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        selected_facts=(),
        execution_facts=(),
        conversation_frame=("cloture sociale",),
        history_messages=(
            {"role": "assistant", "text": "Tu confirmes qu'on garde vendredi ?"},
            {"role": "user", "text": "Okay chef"},
        ),
        coach_summary="Objectif: construire 10 km regulier. Style: direct.",
        allowed_tools=(),
        tool_choice="none",
    )
    bundle = build_layered_conversation_prompt(
        user_text="Okay chef",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi 8 mai 2026.",
        profile_summary="Objectif: construire 10 km regulier. Style: direct.",
        timeline_summary="- Vendredi 8 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="References temporelles resolues: aujourd'hui = 2026-05-08.",
        activity_claim_summary="Claims recents: aucun claim non resolu.",
        signal_summary="Signal: aucun.",
        conversation_history=[
            {"role": "assistant", "text": "Tu confirmes qu'on garde vendredi ?"},
            {"role": "user", "text": "Okay chef"},
        ],
        coach_context={"turn_primary_intent": "close_turn"},
        selected_facts=[],
        context_pack=context_pack,
    )
    return _render_bundle_snapshot(
        route="conversation_close_turn",
        output_schema="CoachDecision",
        bundle=bundle,
    )


def _conversation_casual_chat_snapshot() -> str:
    policy = select_conversation_prompt_policy(intent=IntentCategory.CASUAL_CHAT)
    context_pack = build_conversation_context_pack(
        route="conversation_casual_chat",
        intent="casual_chat",
        capability="terminal_text",
        time_context={"today": "2026-05-08"},
        temporal_summary="References temporelles resolues: aujourd'hui = 2026-05-08.",
        timeline_summary="- Vendredi 8 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        selected_facts=(),
        execution_facts=(),
        conversation_frame=("banter leger sans demande planning",),
        history_messages=(
            {"role": "assistant", "text": "Vendredi footing easy, tu gardes ca propre."},
            {"role": "user", "text": "Tu m'as fumé avec ton plan là"},
        ),
        coach_summary="Objectif: construire 10 km regulier. Style: direct.",
        allowed_tools=(),
        tool_choice="none",
    )
    bundle = build_layered_conversation_prompt(
        user_text="Tu m'as fumé avec ton plan là",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi 8 mai 2026.",
        profile_summary="Objectif: construire 10 km regulier. Style: direct.",
        timeline_summary="- Vendredi 8 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="References temporelles resolues: aujourd'hui = 2026-05-08.",
        activity_claim_summary="Claims recents: aucun claim non resolu.",
        signal_summary="Signal: aucun.",
        conversation_history=[
            {"role": "assistant", "text": "Vendredi footing easy, tu gardes ca propre."},
            {"role": "user", "text": "Tu m'as fumé avec ton plan là"},
        ],
        coach_context={"turn_primary_intent": "casual_chat"},
        selected_facts=[],
        context_pack=context_pack,
    )
    return _render_bundle_snapshot(
        route="conversation_casual_chat",
        output_schema="CoachDecision",
        bundle=bundle,
    )


def test_conversation_plan_lookup_prompt_snapshot() -> None:
    snapshot_path = SNAPSHOT_DIR / "conversation_plan_lookup.txt"
    expected = snapshot_path.read_text()

    assert _conversation_plan_lookup_snapshot() == expected


def test_conversation_close_turn_prompt_snapshot() -> None:
    snapshot_path = SNAPSHOT_DIR / "conversation_close_turn.txt"
    expected = snapshot_path.read_text()

    assert _conversation_close_turn_snapshot() == expected


def test_conversation_casual_chat_prompt_snapshot() -> None:
    snapshot_path = SNAPSHOT_DIR / "conversation_casual_chat.txt"
    expected = snapshot_path.read_text()

    assert _conversation_casual_chat_snapshot() == expected
