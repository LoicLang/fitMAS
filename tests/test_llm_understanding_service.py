from __future__ import annotations

from fitmas.decision import CoachUnderstanding
from fitmas.llm.understanding_service import (
    LLMUnderstandingService,
    UnderstandingRequest,
    parse_coach_understanding_payload,
)


def test_parse_coach_understanding_payload_accepts_minimal_answer() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_lookup",
            "confidence": 0.91,
            "user_summary": "demande le plan de demain",
            "extracted_signals": [],
            "requested_change": None,
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert isinstance(understanding, CoachUnderstanding)
    assert understanding.intent == "plan_lookup"
    assert understanding.confidence == 0.91
    assert understanding.extracted_signals == ()


def test_parse_coach_understanding_payload_accepts_requested_change_and_signal() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "veut deplacer la seance dure a vendredi",
            "extracted_signals": [
                {
                    "type": "readiness",
                    "label": "fatigue",
                    "status": "new",
                    "severity": "moderate",
                    "confidence": 0.8,
                    "evidence": "mal dormi",
                    "payload": {"affects": ["training_load"]},
                }
            ],
            "requested_change": {
                "kind": "move",
                "source_ref": "seance dure de ce soir",
                "target_ref": "vendredi",
                "desired_sport": None,
                "desired_duration_min": None,
                "desired_intensity": None,
                "reason": "fatigue",
                "risk_signals": ["fatigue"],
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.intent == "plan_change"
    assert understanding.extracted_signals[0].type == "readiness"
    assert understanding.extracted_signals[0].payload["affects"] == ["training_load"]
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "move"
    assert understanding.requested_change.target_ref == "vendredi"


def test_parse_coach_understanding_payload_normalizes_typed_session_ref_aliases() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "deplace la seance 3",
            "extracted_signals": [],
            "requested_change": {
                "kind": "move",
                "source_ref": "session:3",
                "target_ref": "date:2026-05-18",
                "reason": "demande typee",
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.requested_change is not None
    assert understanding.requested_change.source_ref == "session_id:3"
    assert understanding.requested_change.target_ref == "date:2026-05-18"


def test_parse_coach_understanding_payload_normalizes_underscore_ref_aliases() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "deplace la seance 3",
            "extracted_signals": [],
            "requested_change": {
                "kind": "move",
                "source_ref": "session_3",
                "target_ref": "date_2026-05-18",
                "reason": "demande typee",
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.requested_change is not None
    assert understanding.requested_change.source_ref == "session_id:3"
    assert understanding.requested_change.target_ref == "date:2026-05-18"


def test_parse_coach_understanding_payload_fills_missing_source_ref_from_typed_signal() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "deplace la seance 3",
            "extracted_signals": [
                {
                    "type": "planning",
                    "label": "move_session",
                    "status": "new",
                    "severity": "low",
                    "confidence": 0.9,
                    "payload": {"target_session_id": 3},
                }
            ],
            "requested_change": {
                "kind": "move",
                "source_ref": None,
                "target_ref": "date:2026-05-18",
                "reason": "demande typee",
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.requested_change is not None
    assert understanding.requested_change.source_ref == "session_id:3"
    assert understanding.requested_change.target_ref == "date:2026-05-18"


def test_parse_coach_understanding_payload_normalizes_day_iso_ref_as_date() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "deplace la seance 3",
            "extracted_signals": [],
            "requested_change": {
                "kind": "move",
                "source_ref": "session_id:3",
                "target_ref": "day:2026-05-18",
                "reason": "demande typee",
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.requested_change is not None
    assert understanding.requested_change.target_ref == "date:2026-05-18"


def test_parse_coach_understanding_payload_normalizes_structured_ref_objects() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "plan_change",
            "confidence": 0.86,
            "user_summary": "deplace la seance 3",
            "extracted_signals": [],
            "requested_change": {
                "kind": "move",
                "source_ref": {"session_id": 3},
                "target_ref": {"date": "2026-05-18"},
                "reason": "demande typee",
            },
            "pending_resolution": None,
            "clarification_need": None,
        }
    )

    assert understanding is not None
    assert understanding.requested_change is not None
    assert understanding.requested_change.source_ref == "session_id:3"
    assert understanding.requested_change.target_ref == "date:2026-05-18"


def test_parse_coach_understanding_payload_rejects_visible_reply_and_patch_fields() -> None:
    assert parse_coach_understanding_payload({"intent": "plan_lookup", "reply_text": "Salut"}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "fitmas_message": "Je bouge ca"}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "plan_patch": {"operations": []}}) is None
    assert parse_coach_understanding_payload({"intent": "plan_change", "commands": []}) is None


def test_parse_coach_understanding_payload_drops_cross_intent_planning_noise() -> None:
    understanding = parse_coach_understanding_payload(
        {
            "intent": "execution_report",
            "confidence": 0.9,
            "user_summary": "seance ratee hier",
            "extracted_signals": [],
            "requested_change": {
                "kind": "move",
                "source_ref": "hier",
                "target_ref": "aujourd'hui",
                "reason": "bruit du modele",
            },
            "pending_resolution": {
                "type": "accept_pending",
                "reason": "bruit du modele",
            },
            "clarification_need": {
                "question": "bruit du modele",
                "missing_fields": ["target"],
            },
        }
    )

    assert understanding is not None
    assert understanding.intent == "execution_report"
    assert understanding.requested_change is None
    assert understanding.pending_resolution is None
    assert understanding.clarification_need is None


def test_llm_understanding_service_calls_prompt_and_request_json() -> None:
    calls: list[dict] = []

    def fake_request_json(**kwargs):
        calls.append(kwargs)
        return {
            "intent": "general_answer",
            "confidence": 0.72,
            "user_summary": "question generale",
            "extracted_signals": [],
            "requested_change": None,
            "pending_resolution": None,
            "clarification_need": None,
        }

    service = LLMUnderstandingService(request_json_fn=fake_request_json)
    result = service.understand(
        UnderstandingRequest(
            event_summary="source=telegram type=user_message text=ok",
            context_blocks=("Plan compact: repos demain",),
        )
    )

    assert result is not None
    assert result.intent == "general_answer"
    assert calls
    assert calls[0]["schema_hint"] == "CoachUnderstanding"
    assert "Tu ne parles pas au user" in calls[0]["system"]
