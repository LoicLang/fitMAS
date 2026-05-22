from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_legacy_user_indication_modules_are_removed() -> None:
    removed = (
        "user_indication_llm.py",
        "user_indications.py",
        "replan_from_life_change.py",
        "tool_routing.py",
    )

    for relative_path in removed:
        assert not (SRC / relative_path).exists()


def test_conversation_pipeline_has_no_deterministic_user_text_gates() -> None:
    source = _source("conversation_pipeline.py")

    forbidden = (
        "interpret_user_indication",
        "user_indication",
        "UserIndicationKind",
        "supports_planning_resolution",
        "maybe_replan_from_user_indication",
        "build_availability_fact_payloads_from_indication",
        "build_health_fact_payloads_from_indication",
        "_resolved_non_completion_from_indication",
        "_resolved_activity_from_indication",
        "_execution_contestation_reply",
        "_week_scope_reply",
        "_no_candidate_constraint_reply",
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


def test_legacy_llm_decide_path_is_deleted() -> None:
    assert not (SRC / "llm/decision_legacy.py").exists()


def test_tools_routing_has_no_user_text_classifier() -> None:
    source = _source("tools/routing.py")

    forbidden = (
        "classify_intent",
        "route_tools_for_query",
        "user_text",
        "_matches_any",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_message_route_runtime_dependencies_do_not_include_user_indication_prestep() -> None:
    source = _source("app/api/routes_messages.py")

    forbidden = (
        "from fitmas.user_indications",
        "from fitmas.user_indication_llm import interpret_user_indication",
        "def interpret_user_indication",
        "interpret_user_indication=interpret_user_indication",
    )

    for symbol in forbidden:
        assert symbol not in source


def test_conversation_dependencies_do_not_expose_user_indication_prestep() -> None:
    source = _source("decision/conversation_contract.py")

    forbidden = (
        "interpret_user_indication",
    )

    for symbol in forbidden:
        assert symbol not in source
