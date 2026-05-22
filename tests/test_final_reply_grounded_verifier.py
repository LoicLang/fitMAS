from __future__ import annotations

from datetime import date

from fitmas.llm.reply_backend import compose_plan_lookup_reply, verify_factual_reply
from fitmas.decision.grounding import PlanWindowFact, ReplyGroundingPacket


def _packet() -> ReplyGroundingPacket:
    return ReplyGroundingPacket(
        local_date=date(2026, 5, 7),
        timezone_name="Europe/Paris",
        plan_window=(
            PlanWindowFact(
                session_id=46,
                scheduled_date=date(2026, 5, 8),
                day_label="vendredi",
                sport="running",
                title="Footing Z2",
                duration_min=40,
                intensity="easy",
                completion_status="adapted",
                slot_kind="training",
            ),
        ),
    )


def test_factual_verifier_repairs_reply_against_grounding_packet() -> None:
    calls: list[str] = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        assert "Grounding autoritaire" in kwargs["prompt"]
        assert "2026-05-08 (vendredi)" in kwargs["prompt"]
        return (
            '{"verdict":"repair","reason":"vendredi faux",'
            '"repaired_reply":"Vendredi, tu as le footing Z2 de 40 minutes."}'
        )

    reply = verify_factual_reply(
        "Vendredi est vide.",
        grounding=_packet(),
        pipeline_capability="plan_lookup",
        request_text_fn=fake_request_text,
    )

    assert reply == "Vendredi, tu as le footing Z2 de 40 minutes."
    assert calls


def test_factual_hard_guard_rejects_verifier_allow_with_wrong_duration() -> None:
    def fake_request_text(**kwargs):
        return '{"verdict":"allow","reason":"ok","repaired_reply":""}'

    reply = verify_factual_reply(
        "Vendredi, tu as le footing Z2 de 50 minutes.",
        grounding=_packet(),
        pipeline_capability="plan_lookup",
        request_text_fn=fake_request_text,
    )

    assert reply is None


def test_plan_lookup_uses_semantic_verifier_not_original_token_guard() -> None:
    request_calls = 0

    def fake_request_text(**kwargs):
        nonlocal request_calls
        request_calls += 1
        if "Grounding autoritaire" in kwargs["prompt"]:
            return (
                '{"verdict":"repair","reason":"brouillon contredit le plan",'
                '"repaired_reply":"Vendredi, tu as le footing Z2 de 40 minutes."}'
            )
        return "Vendredi est vide."

    reply = compose_plan_lookup_reply(
        user_text="J'ai quoi vendredi ?",
        original_llm_reply="Vendredi repos.",
        grounding=_packet(),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Vendredi, tu as le footing Z2 de 40 minutes."
    assert request_calls == 2


def test_plan_lookup_grounding_falls_back_to_db_summary_when_verifier_cannot_repair() -> None:
    def fake_request_text(**kwargs):
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"ok","repaired_reply":""}'
        return "Vendredi, tu as le footing Z2 de 50 minutes."

    reply = compose_plan_lookup_reply(
        user_text="J'ai quoi vendredi ?",
        original_llm_reply="Vendredi, tu as le footing Z2 de 50 minutes.",
        grounding=_packet(),
        request_text_fn=fake_request_text,
        verifier_text_fn=fake_request_text,
    )

    assert reply == "Vendredi: Footing Z2, running, 40 min, statut adapted."
