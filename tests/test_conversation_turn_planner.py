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
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return {
            "primary_intent": "availability_constraint",
            "secondary_intents": [],
            "user_goal": "signaler une indisponibilite demain soir",
            "mutation_signal": False,
            "execution_claim": None,
            "availability_constraint": {
                "availability": "unavailable",
                "sport_type": "swimming",
                "starts_on": "2026-05-13",
                "ends_on": "2026-05-27",
                "scope": "sport",
            },
            "temporal_references": [{"kind": "relative_day", "value": "tomorrow", "role": "context"}],
            "requires_truth_read": True,
            "truth_scope": "plan_window",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.88,
        }

    monkeypatch.setattr(
        planner.gw,
        "request_json",
        fake_request_json,
    )

    turn_plan = planner.plan_conversation_turn(
        user_text="Demain soir c'est impossible pour moi",
        temporal_summary="demain = 2026-05-13, soir = evening",
        execution_summary="seances planifiees dans la fenetre",
        activity_claim_summary="Claim: aucun",
        signal_summary="Signal: aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "availability_constraint"
    assert turn_plan.has_plan_mutation is False
    assert turn_plan.availability_constraint["sport_type"] == "swimming"
    assert turn_plan.availability_constraint["ends_on"] == "2026-05-27"
    assert turn_plan.requires_truth_read is True
    assert turn_plan.truth_scope == "plan_window"
    assert "Availability constraint" in captured["prompt"]
    assert "disponibilite datee claire" in captured["system"]
    assert "Demain soir c'est impossible pour moi" in captured["prompt"]


def test_turn_plan_can_carry_grounding_requirements() -> None:
    plan = planner.ConversationTurnPlan(
        primary_intent="plan_mutation",
        user_goal="deplacer la seance de demain a vendredi",
        mutation_signal=True,
        temporal_references=(
            {"kind": "relative_day", "value": "tomorrow", "role": "source"},
            {"kind": "weekday", "value": "friday", "role": "target"},
        ),
        requires_truth_read=True,
        truth_scope="plan_window",
        confidence=0.91,
    )

    assert plan.temporal_references[0]["kind"] == "relative_day"
    assert plan.temporal_references[1]["value"] == "friday"
    assert plan.requires_truth_read is True
    assert plan.truth_scope == "plan_window"


def test_plan_conversation_turn_accepts_execution_report_as_secondary(monkeypatch) -> None:
    monkeypatch.setattr(
        planner.gw,
        "request_json",
        lambda **kwargs: {
            "primary_intent": "health_signal",
            "secondary_intents": ["execution_report"],
            "user_goal": "signaler fatigue apres une seance faite",
            "mutation_signal": False,
            "execution_claim": {
                "status": "done",
                "sport_type": "running",
                "date": "2026-05-08",
            },
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.84,
        },
    )

    turn_plan = planner.plan_conversation_turn(
        user_text="J'ai couru mais jambes lourdes",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="Footing planned",
        activity_claim_summary="Claim: running fait aujourd'hui",
        signal_summary="Signal: fatigue jambes",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "health_signal"
    assert turn_plan.secondary_intents == ("execution_report",)


def test_plan_conversation_turn_accepts_generic_body_metric_question(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["prompt"] = prompt
        return {
            "primary_intent": "generic_question",
            "secondary_intents": [],
            "user_goal": "demander quoi faire apres une pesee a 100 kg",
            "mutation_signal": False,
            "execution_claim": None,
            "requires_truth_read": False,
            "truth_scope": "memory",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.82,
        }

    monkeypatch.setattr(planner.gw, "request_json", fake_request_json)

    turn_plan = planner.plan_conversation_turn(
        user_text="Putain enft je fais 100kg qu'est ce qu'on fait ?",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="aucun",
        activity_claim_summary="aucun",
        signal_summary="aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "generic_question"
    assert turn_plan.has_plan_mutation is False
    assert "100kg" in captured["prompt"]
    assert "generic_question" in captured["prompt"]


def test_plan_conversation_turn_routes_activity_highlights(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return {
            "primary_intent": "activity_highlights",
            "secondary_intents": [],
            "user_goal": "connaitre la plus longue sortie recente",
            "mutation_signal": False,
            "execution_claim": None,
            "requires_truth_read": True,
            "truth_scope": "execution",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.86,
        }

    monkeypatch.setattr(planner.gw, "request_json", fake_request_json)

    turn_plan = planner.plan_conversation_turn(
        user_text="C'etait quoi ma plus longue sortie recente ?",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="activites recentes disponibles",
        activity_claim_summary="aucun",
        signal_summary="aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "activity_highlights"
    assert turn_plan.requires_truth_read is True
    assert turn_plan.truth_scope == "execution"
    assert "activity_highlights" in captured["prompt"]
    assert "plus longue sortie" in captured["system"]


def test_plan_conversation_turn_accepts_generic_question_as_secondary(monkeypatch) -> None:
    monkeypatch.setattr(
        planner.gw,
        "request_json",
        lambda **kwargs: {
            "primary_intent": "generic_question",
            "secondary_intents": ["generic_question"],
            "user_goal": "continuer une question generale sur le poids",
            "mutation_signal": False,
            "execution_claim": None,
            "requires_truth_read": False,
            "truth_scope": "memory",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.78,
        },
    )

    turn_plan = planner.plan_conversation_turn(
        user_text="Je voulais dire c'est pas grave que je fasse 100kg",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="aucun",
        activity_claim_summary="aucun",
        signal_summary="aucun",
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "generic_question"
    assert turn_plan.secondary_intents == ("generic_question",)


def test_plan_conversation_turn_includes_recent_thread_for_elliptic_followup(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return {
            "primary_intent": "generic_question",
            "secondary_intents": [],
            "user_goal": "rassurer sur le poids mentionne au tour precedent",
            "mutation_signal": False,
            "execution_claim": None,
            "requires_truth_read": False,
            "truth_scope": "memory",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.81,
        }

    monkeypatch.setattr(planner.gw, "request_json", fake_request_json)

    turn_plan = planner.plan_conversation_turn(
        user_text="Rien de grave quoi",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="Footing planned",
        activity_claim_summary="aucun",
        signal_summary="aucun",
        conversation_history=[
            {"role": "user", "text": "Putain enft je fais 100kg qu'est ce qu'on fait ?"},
            {"role": "assistant", "text": "100kg, c'est une donnee, pas un verdict."},
        ],
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "generic_question"
    assert "Fil conversationnel recent" in captured["prompt"]
    assert "100kg, c'est une donnee" in captured["prompt"]
    assert "messages courts ou elliptiques" in captured["system"]


def test_plan_conversation_turn_prompts_bare_day_without_thread_as_clarification(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_request_json(*, system, prompt, model, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return {
            "primary_intent": "needs_clarification",
            "secondary_intents": [],
            "user_goal": "message elliptique avec seulement un jour",
            "mutation_signal": False,
            "execution_claim": None,
            "temporal_references": [{"kind": "weekday", "value": "saturday", "role": "context"}],
            "requires_truth_read": False,
            "truth_scope": None,
            "needs_clarification": True,
            "clarification_question": "Tu parles de quoi pour samedi ?",
            "confidence": 0.76,
        }

    monkeypatch.setattr(planner.gw, "request_json", fake_request_json)

    turn_plan = planner.plan_conversation_turn(
        user_text="samedi",
        temporal_summary="aujourd'hui = 2026-05-08",
        execution_summary="Plan semaine disponible",
        activity_claim_summary="aucun",
        signal_summary="aucun",
        conversation_history=[],
    )

    assert turn_plan is not None
    assert turn_plan.primary_intent == "needs_clarification"
    assert turn_plan.has_plan_mutation is False
    assert turn_plan.temporal_references[0]["role"] == "context"
    assert "jour/date seul" in captured["system"]
    assert "Fil conversationnel recent=aucun" in captured["system"]
    assert "question de choix planning" in captured["system"]
