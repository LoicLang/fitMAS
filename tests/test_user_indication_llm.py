from __future__ import annotations

from datetime import date

import fitmas.user_indication_llm as indication_llm
from fitmas.user_indication_llm import _prefer_richer_indication
from fitmas.user_indications import (
    IndicationTimeReference,
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
)


def test_prefers_fallback_when_it_has_richer_time_resolution():
    llm_indication = UserIndication(
        kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
        confidence=0.72,
        source_text="Cette semaine je voyage de mercredi a vendredi",
        scope=UserIndicationScope.UNKNOWN,
        polarity=UserIndicationPolarity.UNAVAILABLE,
        time_reference=None,
    )
    fallback = UserIndication(
        kind=UserIndicationKind.AVAILABILITY_CONSTRAINT,
        confidence=0.87,
        source_text="Cette semaine je voyage de mercredi a vendredi",
        scope=UserIndicationScope.WEEK,
        polarity=UserIndicationPolarity.UNAVAILABLE,
        time_reference=IndicationTimeReference(
            label="explicit_wednesday",
            resolved_date=date(2026, 4, 1),
            day_key="wednesday",
            relative_reference="explicit_wednesday",
            window=None,
        ),
    )

    selected = _prefer_richer_indication(llm_indication, fallback)

    assert selected == fallback


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
