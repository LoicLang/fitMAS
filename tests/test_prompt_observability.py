from fitmas.llm.prompt_observability import (
    DecideFailureReason,
    build_prompt_trace,
    normalize_decide_failure_reason,
)
from fitmas.context_pack import build_conversation_context_pack
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt
from fitmas.tools.routing import IntentCategory


def test_build_prompt_trace_counts_system_and_user_chars() -> None:
    trace = build_prompt_trace(
        route="conversation_decide",
        provider="deepseek",
        model="deepseek-chat",
        prompt_policy="plan_lookup_compact",
        prompt_contract=None,
        intent="plan_lookup",
        system=[{"type": "text", "text": "system A"}, {"type": "text", "text": "system B"}],
        user_prompt="hello user",
        tool_names=("get_plan_window",),
        truth_block_names=("temporal", "planning"),
        history_messages_used=2,
    )

    assert trace.route == "conversation_decide"
    assert trace.system_chars == len("system A") + len("system B")
    assert trace.user_chars == len("hello user")
    assert trace.total_chars == trace.system_chars + trace.user_chars
    assert trace.tool_names == ("get_plan_window",)
    assert trace.truth_block_names == ("temporal", "planning")
    assert trace.history_messages_used == 2


def test_normalize_decide_failure_reason_accepts_known_values_only() -> None:
    assert normalize_decide_failure_reason("empty_output") == DecideFailureReason.EMPTY_OUTPUT
    assert normalize_decide_failure_reason("not-a-real-reason") == DecideFailureReason.UNKNOWN


def test_layered_prompt_bundle_exposes_trace_metadata() -> None:
    policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    context_pack = build_conversation_context_pack(
        route="conversation_plan_lookup",
        intent="plan_lookup",
        capability="read_only",
        time_context={"today": "vendredi"},
        temporal_summary="Aujourd'hui: vendredi",
        timeline_summary="- Vendredi: Footing 40 min",
        allowed_tools=("get_plan_window",),
    )
    bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi",
        timeline_summary="- Vendredi: Footing 40 min",
        execution_summary=None,
        temporal_summary=None,
        activity_claim_summary=None,
        signal_summary=None,
        conversation_history=[],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=[],
        context_pack=context_pack,
    )

    assert bundle.trace is not None
    assert bundle.trace.prompt_policy == "plan_lookup_compact"
    assert bundle.trace.prompt_contract == "conversation_plan_lookup"
    assert bundle.trace.intent == "plan_lookup"
    assert bundle.trace.tool_names == ("get_plan_window",)
    assert bundle.trace.truth_block_names == (
        "temporal",
        "plan_window",
        "execution_reality",
        "activity_claims",
    )
    assert bundle.trace.total_chars > 0


def test_layered_prompt_filters_rendered_layers_by_contract() -> None:
    close_policy = select_conversation_prompt_policy(intent=IntentCategory.CLOSE_TURN)
    close_bundle = build_layered_conversation_prompt(
        user_text="Okay chef",
        prompt_policy=close_policy,
        time_block="Aujourd'hui: vendredi",
        profile_summary="Objectif: construire 10 km regulier. Style: direct.",
        timeline_summary="- Vendredi: Footing 40 min",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="aujourd'hui = vendredi",
        activity_claim_summary="Claims recents: aucun",
        signal_summary="Signal: aucun.",
        conversation_history=[
            {"role": "assistant", "text": "Vendredi footing easy."},
            {"role": "user", "text": "Okay chef"},
        ],
        coach_context={"turn_primary_intent": "close_turn"},
        selected_facts=["objectif 10 km"],
    )
    close_system = "\n\n".join(str(part.get("text") or "") for part in close_bundle.system)

    assert close_system.count("Tu es FitMAS") == 1
    assert "Profil resume:" not in close_system
    assert "Calendrier date reel:" not in close_system
    assert "Execution recente:" not in close_system
    assert "Memoire utile" not in close_system
    assert "Historique recent:" in close_system

    lookup_policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    lookup_bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=lookup_policy,
        time_block="Aujourd'hui: vendredi",
        profile_summary="Objectif: construire 10 km regulier. Style: direct.",
        timeline_summary="- Samedi: Footing 40 min",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="demain = samedi",
        activity_claim_summary="Claims recents: aucun",
        signal_summary="Signal: aucun.",
        conversation_history=[
            {"role": "assistant", "text": "Vendredi repos."},
            {"role": "user", "text": "Ok"},
        ],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=["objectif 10 km"],
    )
    lookup_system = "\n\n".join(str(part.get("text") or "") for part in lookup_bundle.system)

    assert lookup_system.count("Tu es FitMAS") == 1
    assert "Profil resume:" not in lookup_system
    assert "Memoire utile" not in lookup_system
    assert "Calendrier date reel:" in lookup_system
    assert "Execution recente:" in lookup_system
    assert "Historique recent:" in lookup_system


def test_layered_prompt_keeps_rendered_truth_out_of_user_prompt() -> None:
    policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi 8 mai 2026.",
        timeline_summary="- Samedi 9 mai: Footing endurance, 40 min, Z2, planned.",
        execution_summary="Execution recente: hier repos tenu.",
        temporal_summary="References temporelles resolues: demain = 2026-05-09.",
        activity_claim_summary="Claims recents: aucun claim non resolu.",
        signal_summary=None,
        conversation_history=[
            {"role": "assistant", "text": "Vendredi tu souffles, samedi footing Z2."},
            {"role": "user", "text": "Ok."},
        ],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=[],
    )
    system_text = "\n\n".join(str(part.get("text") or "") for part in bundle.system)

    assert "Source de verite planning conversationnelle" in system_text
    assert "Calendrier date reel:" in system_text
    assert "Source de vérité planning conversationnelle" not in bundle.prompt
    assert "Calendrier daté utile:" not in bundle.prompt
    assert bundle.prompt == "Nouveau message de l'utilisateur:\nJ'ai quoi demain ?"
