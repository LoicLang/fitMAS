from pathlib import Path

from fitmas.context_pack import build_conversation_context_pack
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt
from fitmas.tools.routing import IntentCategory


SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "prompts"


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
    trace = bundle.trace.as_dict() if bundle.trace else {}
    system = "\n\n--- SYSTEM PART ---\n\n".join(str(part.get("text") or "") for part in bundle.system)
    return "\n".join(
        (
            "route: conversation_plan_lookup",
            f"contract: {trace.get('prompt_contract') or 'none'}",
            f"tool_budget: {list(trace.get('tool_names') or ())}",
            f"truth_blocks: {list(trace.get('truth_block_names') or ())}",
            "output_schema: CoachDecision",
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


def test_conversation_plan_lookup_prompt_snapshot() -> None:
    snapshot_path = SNAPSHOT_DIR / "conversation_plan_lookup.txt"
    expected = snapshot_path.read_text()

    assert _conversation_plan_lookup_snapshot() == expected
