from __future__ import annotations

from fitmas import conversation_turn_planner as planner


def test_plan_conversation_turn_parses_compound_intent(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return {
            "primary_intent": "plan_mutation",
            "secondary_intents": ["non_completion_claim"],
            "user_goal": "echanger la natation d'aujourd'hui avec vendredi",
            "mutation_signal": True,
            "execution_claim": {
                "status": "not_done",
                "sport_type": "swimming",
                "date": "2026-04-15",
            },
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.91,
        }

    monkeypatch.setattr(planner.gw, "request_json", fake_request_json)

    turn_plan = planner.plan_conversation_turn(
        user_text="Piscine impossible ce matin, vendredi a la place ?",
        temporal_summary="aujourd'hui = 2026-04-15",
        execution_summary="Natation CSS planned",
        activity_claim_summary="Claim: non realisation swimming 2026-04-15",
        signal_summary="Signal: aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "plan_mutation"
    assert turn_plan.secondary_intents == ("non_completion_claim",)
    assert turn_plan.has_plan_mutation is True
    assert turn_plan.execution_claim["status"] == "not_done"
    assert "capabilities" in captured["prompt"]
    assert "Aucun write" in captured["system"]


def test_plan_conversation_turn_rejects_invalid_payload(monkeypatch) -> None:
    monkeypatch.setattr(planner.gw, "request_json", lambda **kwargs: {"primary_intent": "nonsense"})

    turn_plan = planner.plan_conversation_turn(
        user_text="Piscine impossible ce matin, vendredi a la place ?",
        temporal_summary="aujourd'hui = 2026-04-15",
        execution_summary="Natation CSS planned",
        activity_claim_summary="Claim: non realisation swimming 2026-04-15",
        signal_summary="Signal: aucun",
    )

    assert turn_plan is None


def test_plan_conversation_turn_accepts_availability_constraint(monkeypatch) -> None:
    monkeypatch.setattr(
        planner.gw,
        "request_json",
        lambda **kwargs: {
            "primary_intent": "availability_constraint",
            "secondary_intents": [],
            "user_goal": "signaler un voyage cette semaine",
            "mutation_signal": False,
            "execution_claim": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.87,
        },
    )

    turn_plan = planner.plan_conversation_turn(
        user_text="Cette semaine je voyage de mercredi a vendredi",
        temporal_summary="mercredi a vendredi",
        execution_summary="seances planifiees dans la fenetre",
        activity_claim_summary="Claim: aucun",
        signal_summary="Signal: aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "availability_constraint"
    assert turn_plan.has_plan_mutation is False
