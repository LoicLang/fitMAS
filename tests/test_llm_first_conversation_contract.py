from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_conversation_pipeline_has_no_deterministic_user_text_gates() -> None:
    source = _source("conversation_pipeline.py")

    forbidden = (
        "parse_confirmation_reply(",
        "_maybe_low_signal_label(",
        "_has_rich_signal_marker(",
        "_looks_like_plan_mutation_request(",
        "_looks_like_swap_request(",
        "_sanitize_no_change_reply(",
        "maybe_replan_from_life_change(",
        "build_claim_memory_updates(",
        "_should_run_post_reply_health_adaptation(",
        "_can_auto_apply_health_suggestion(",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_conversation_context_does_not_parse_free_user_text() -> None:
    source = _source("conversation_context.py")

    forbidden = (
        "extract_activity_claim",
        "extract_recent_activity_claim",
        "extract_non_completion_claim",
        "is_activity_claim_correction",
        "resolve_temporal_context(\n            user_text",
        "current_activity_claim",
        "recent_activity_claim",
        "non_completion_claim",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_user_indication_llm_has_no_deterministic_fallback_or_lexical_hints() -> None:
    source = _source("user_indication_llm.py")

    forbidden = (
        "fallback_interpret_user_indication",
        "_closed_protocol_fallback",
        "_lexical_hint_block",
        "_prefer_richer_indication",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_user_indications_module_has_no_free_text_fallback_parser() -> None:
    source = _source("user_indications.py")

    forbidden = (
        "fallback_interpret_user_indication",
        "extract_activity_claim",
        "extract_non_completion_claim",
        "_fallback_availability_indication",
        "_fallback_health_indication",
        "_UNAVAILABLE_PATTERNS",
        "_HEALTH_PATTERNS",
        "source_text_normalized",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_llm_decide_does_not_route_tools_from_raw_user_text() -> None:
    source = _source("llm.py")

    forbidden = (
        "route_tools_for_query(user_text",
        "_fallback_extract_facts(user_text",
    )

    for symbol in forbidden:
        assert symbol not in source
