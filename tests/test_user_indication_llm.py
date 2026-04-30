from __future__ import annotations

import fitmas.user_indication_llm as indication_llm


def test_interpret_user_indication_does_not_use_removed_richness_fallback():
    assert not hasattr(indication_llm, "_prefer_richer_indication")


def test_interpret_user_indication_runs_llm_with_clarification_context(monkeypatch):
    captured: dict[str, str] = {}

    monkeypatch.setattr(indication_llm.gw, "client", lambda: object())

    def fake_request_json(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return {
            "kind": "execution_update",
            "confidence": 0.92,
            "scope": "single_day",
            "polarity": "signal",
            "time_reference": {
                "label": "clarification",
                "resolved_date": "2026-03-31",
                "day_key": "tuesday",
                "relative_reference": "yesterday",
                "window": None,
            },
            "execution": {
                "sport_type": "strength",
                "duration_min": None,
                "status": "not_done",
            },
            "followup_needed": False,
            "followup_reason": None,
        }

    monkeypatch.setattr(indication_llm.gw, "request_json", fake_request_json)

    indication = indication_llm.interpret_user_indication(
        "Non",
        timezone_name="Europe/Paris",
        recent_agent_text="Je ne vois pas de trace de ton renfo hier. Tu l'as faite ou non ?",
        clarification_date="2026-03-31",
        clarification_sport_type="strength",
    )

    assert "Contexte de clarification active" in captured["prompt"]
    assert indication is not None
    assert indication.execution_completed is False
    assert indication.execution_sport_type == "strength"
