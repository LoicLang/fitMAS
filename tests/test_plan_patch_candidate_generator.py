from __future__ import annotations

from fitmas.plan_patch_candidate_generator import (
    CandidateGenerationInput,
    generate_plan_patch_candidates,
)


def test_candidate_generator_parses_bounded_llm_candidates() -> None:
    calls: list[dict] = []

    def _request_json(**kwargs):
        calls.append(kwargs)
        return {
            "candidates": [
                {
                    "patches": [
                        {
                            "coach_message": "Candidate only.",
                            "operations": [
                                {
                                    "operation_type": "move_session",
                                    "target_session_id": 42,
                                    "target_date": "2099-05-08",
                                    "rationale": "User can train Friday.",
                                }
                            ],
                        }
                    ],
                    "rationale": "Move the requested session to the available slot.",
                    "expected_tradeoff": "Recovery must be rescored.",
                    "confidence": 0.84,
                    "assumptions": ["User means session 42."],
                    "risk_notes": ["Check hard-session spacing."],
                }
            ]
        }

    result = generate_plan_patch_candidates(
        CandidateGenerationInput(
            user_message="deplace la seance a vendredi",
            parsed_user_intent={"primary_intent": "plan_mutation"},
            current_plan_summary={"sessions": [{"id": 42, "day": "thursday"}]},
            current_plan_id="plan_123",
            current_plan_version=7,
            constraints={},
            week_facts={"hard_sessions_after": 1},
            coherence_findings=(),
            allowed_operations=("move_session", "update_session"),
            forbidden_operations=("create_session",),
            pending_context=None,
        ),
        request_json_fn=_request_json,
    )

    assert len(result) == 1
    assert result[0].created_from_plan_id == "plan_123"
    assert result[0].created_from_plan_version == 7
    assert result[0].patches[0].operations[0].operation_type == "move_session"
    assert "Tu ne parles jamais a l'utilisateur" in calls[0]["system"]
    assert "move_session" in calls[0]["prompt"]
    assert "create_session" in calls[0]["prompt"]


def test_candidate_generator_accepts_backend_candidate_ref_without_patch_copy() -> None:
    calls: list[dict] = []

    def _request_json(**kwargs):
        calls.append(kwargs)
        return {
            "candidates": [
                {
                    "candidate_ref": "backend:move_session:42:2099-05-08",
                    "rationale": "Use the backend option for the requested move.",
                    "expected_tradeoff": "Backend validation owns the real consequences.",
                    "confidence": 0.87,
                    "assumptions": ["The user means the dated session."],
                    "risk_notes": [],
                }
            ]
        }

    result = generate_plan_patch_candidates(
        CandidateGenerationInput(
            user_message="deplace la seance a vendredi",
            parsed_user_intent={"primary_intent": "plan_mutation"},
            current_plan_summary={"sessions": [{"id": 42, "day": "thursday"}]},
            current_plan_id="plan_123",
            current_plan_version=7,
            constraints={},
            week_facts=None,
            coherence_findings=(),
            allowed_operations=("move_session", "update_session"),
            forbidden_operations=(),
            pending_context=None,
            backend_candidates=(
                {
                    "candidate_ref": "backend:move_session:42:2099-05-08",
                    "summary": "Move session 42 to Friday.",
                    "operations": ["move_session"],
                },
            ),
        ),
        request_json_fn=_request_json,
    )

    assert len(result) == 1
    assert result[0].candidate_ref == "backend:move_session:42:2099-05-08"
    assert result[0].patches == ()
    assert "backend_candidates" in calls[0]["prompt"]
    assert "candidate_ref" in calls[0]["prompt"]


def test_candidate_generator_drops_invalid_or_disallowed_candidates_and_caps_to_three() -> None:
    def _request_json(**kwargs):
        del kwargs
        return {
            "candidates": [
                _candidate_payload("move_session", 1),
                _candidate_payload("create_session", 2),
                _candidate_payload("update_session", 3),
                {"patches": "invalid"},
                _candidate_payload("move_session", 4),
                _candidate_payload("move_session", 5),
            ]
        }

    result = generate_plan_patch_candidates(
        CandidateGenerationInput(
            user_message="adapte demain",
            parsed_user_intent={},
            current_plan_summary={},
            current_plan_id="plan_123",
            current_plan_version=7,
            constraints={},
            week_facts=None,
            coherence_findings=(),
            allowed_operations=("move_session", "update_session"),
            forbidden_operations=("create_session",),
            pending_context=None,
        ),
        request_json_fn=_request_json,
    )

    assert len(result) == 3
    assert [
        candidate.patches[0].operations[0].target_session_id
        for candidate in result
    ] == [1, 3, 4]


def test_candidate_generator_enforces_forbidden_operations_even_if_allowed_contains_them() -> None:
    def _request_json(**kwargs):
        del kwargs
        return {
            "candidates": [
                _candidate_payload("create_session", 1),
                _candidate_payload("move_session", 2),
            ]
        }

    result = generate_plan_patch_candidates(
        CandidateGenerationInput(
            user_message="ajoute une seance",
            parsed_user_intent={},
            current_plan_summary={},
            current_plan_id="plan_123",
            current_plan_version=7,
            constraints={},
            week_facts=None,
            coherence_findings=(),
            allowed_operations=("create_session", "move_session"),
            forbidden_operations=("create_session",),
            pending_context=None,
        ),
        request_json_fn=_request_json,
    )

    assert len(result) == 1
    assert result[0].patches[0].operations[0].operation_type == "move_session"


def test_candidate_generator_returns_empty_tuple_on_outage_or_invalid_payload() -> None:
    input_payload = CandidateGenerationInput(
        user_message="adapte",
        parsed_user_intent={},
        current_plan_summary={},
        current_plan_id="plan_123",
        current_plan_version=7,
        constraints={},
        week_facts=None,
        coherence_findings=(),
        allowed_operations=("move_session",),
        forbidden_operations=(),
        pending_context=None,
    )

    assert generate_plan_patch_candidates(input_payload, request_json_fn=lambda **kwargs: None) == ()
    assert generate_plan_patch_candidates(input_payload, request_json_fn=lambda **kwargs: {"candidates": {}}) == ()


def _candidate_payload(operation_type: str, target_session_id: int) -> dict:
    return {
        "patches": [
            {
                "coach_message": "Candidate only.",
                "operations": [
                    {
                        "operation_type": operation_type,
                        "target_session_id": target_session_id,
                        "target_date": "2099-05-08",
                        "rationale": "Candidate rationale.",
                    }
                ],
            }
        ],
        "rationale": "Candidate rationale.",
        "expected_tradeoff": "Candidate tradeoff.",
        "confidence": 0.8,
        "assumptions": [],
        "risk_notes": [],
    }
