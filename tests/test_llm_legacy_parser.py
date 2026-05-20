from __future__ import annotations

from fitmas.legacy.decision_contracts import CoachDecision, MutationDecision
from fitmas.llm.legacy_parser import (
    downgrade_free_confirmation_payload,
    get_last_invalid_decision_payload,
    parse_coach_decision_payload,
    parse_llm_decision_payload,
)


def test_legacy_parser_accepts_coach_decision_with_actions() -> None:
    decision = parse_coach_decision_payload(
        {
            "response_type": "no_change",
            "rationale": "execution manquee sans mutation planning",
            "fitmas_message": "Renfo d'hier note non fait.",
            "execution_actions": [
                {
                    "type": "record_execution_update",
                    "target_session_id": 123,
                    "completed": "false",
                    "confidence": "high",
                }
            ],
            "memory_actions": [
                {
                    "type": "record_health_signal",
                    "health_signal": "fatigue post mauvaise nuit",
                    "signal_kind": "fatigue",
                    "confidence": "medium",
                }
            ],
        }
    )

    assert isinstance(decision, CoachDecision)
    assert decision.execution_actions[0].target_ref == "session_id:123"
    assert decision.execution_actions[0].status == "not_completed"
    assert decision.memory_actions[0].type == "record_health_signal"
    assert decision.memory_actions[0].confidence == 0.65


def test_legacy_parser_accepts_legacy_mutation_and_remembers_invalid_payloads() -> None:
    invalid = parse_llm_decision_payload(
        {
            "mutation_type": "downgrade",
            "rationale": "hors enum",
            "fitmas_message": "On degrade.",
        }
    )
    assert invalid is None
    remembered = get_last_invalid_decision_payload()
    assert remembered is not None
    assert remembered["mutation_type"] == "downgrade"
    assert remembered["rationale"] == "hors enum"
    assert remembered["fitmas_message"] == "On degrade."

    valid = parse_llm_decision_payload(
        {
            "mutation_type": "replace_session",
            "target_date": "2099-04-29",
            "new_sport_type": "running",
            "new_session_type": "easy",
            "new_title": "Footing easy",
            "new_duration_min": 30,
            "rationale": "piscine fermee",
            "fitmas_message": "Je pose un footing easy mercredi.",
        }
    )

    assert isinstance(valid, MutationDecision)
    assert valid.mutation_type == "create_session"
    assert get_last_invalid_decision_payload() is None


def test_legacy_parser_downgrades_free_confirmation_payload() -> None:
    repaired = downgrade_free_confirmation_payload(
        {
            "response_type": "requires_confirmation",
            "rationale": "fatigue signalee",
            "fitmas_message": "On zappe la seance et on remplace par marche.",
            "confirmation_reason": "adaptation sensible",
        }
    )

    assert repaired is not None
    assert repaired["response_type"] == "no_change"
    assert repaired["confirmation_reason"] is None
    assert "Signal pris" in repaired["fitmas_message"]
