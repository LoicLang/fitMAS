from __future__ import annotations

from types import SimpleNamespace

import fitmas.llm.legacy_schema_repair as legacy_schema_repair
from fitmas.tools.contract import ToolResult


def _downgrade(data: dict | None) -> dict | None:
    if data and data.get("response_type") == "requires_confirmation" and not data.get("plan_patch"):
        repaired = dict(data)
        repaired["response_type"] = "no_change"
        repaired["confirmation_reason"] = None
        return repaired
    return data


def test_schema_repair_invalid_payload_uses_injected_request_and_downgrades_free_confirmation() -> None:
    calls: list[str] = []

    def fake_request_structured_json(**kwargs):
        calls.append(str(kwargs["messages"][0]["content"]))
        return {
            "response_type": "requires_confirmation",
            "rationale": "aucun patch structure",
            "fitmas_message": "Je peux echanger si tu confirmes.",
            "confirmation_reason": "option a confirmer",
        }

    data = legacy_schema_repair.repair_invalid_decision_payload(
        data={"response_type": "requires_confirmation"},
        system="system",
        prompt="Je ne suis pas dispo demain",
        request_structured_json_fn=fake_request_structured_json,
        downgrade_free_confirmation_fn=_downgrade,
    )

    assert data is not None
    assert data["response_type"] == "no_change"
    assert data["confirmation_reason"] is None
    assert "PAYLOAD_INVALIDE" in calls[0]


def test_schema_repair_prose_repair_downgrades_free_confirmation_without_patch() -> None:
    data = legacy_schema_repair.repair_decision_json_from_text(
        "Je peux echanger le tempo avec le renfo si tu confirmes.",
        context_prompt="Je ne suis pas dispo demain soir",
        tool_result_summary="- validate_plan_patch: Patch a confirmer.",
        request_structured_json_fn=lambda **_kwargs: {
            "response_type": "requires_confirmation",
            "rationale": "aucune mutation structuree",
            "fitmas_message": "Je peux echanger le tempo avec le renfo si tu confirmes.",
            "confirmation_reason": "swap a confirmer",
        },
        downgrade_free_confirmation_fn=_downgrade,
    )

    assert data is not None
    assert data["response_type"] == "no_change"
    assert data["confirmation_reason"] is None


def test_schema_repair_refuses_provider_tool_markup() -> None:
    data = legacy_schema_repair.repair_decision_json_from_text(
        "<｜dsml｜tool_calls><｜dsml｜invoke name=\"get_plan_window\">",
        request_structured_json_fn=lambda **_kwargs: {"response_type": "no_change"},
        downgrade_free_confirmation_fn=_downgrade,
    )

    assert data is None


def test_schema_repair_tool_result_summary_includes_payloads_not_only_summaries() -> None:
    executions = [
        SimpleNamespace(
            result=ToolResult(
                tool_name="get_plan_window",
                status="ok",
                summary="2 seances.",
                payload={
                    "sessions": [
                        {"id": 11, "scheduled_date": "2099-03-23", "session_title": "Tempo"},
                        {"id": 12, "scheduled_date": "2099-03-25", "session_title": "Renfo"},
                    ]
                },
            )
        )
    ]

    summary = legacy_schema_repair.repair_tool_result_summary(executions)

    assert summary is not None
    assert '"id": 11' in summary
    assert '"session_title": "Renfo"' in summary
    assert "2 seances." in summary
