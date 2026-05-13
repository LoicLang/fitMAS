from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from fitmas.conversation_pipeline import _pending_choice_serialization_candidates
from fitmas.conversation_pipeline import _adaptation_candidate_trace
from fitmas.grounding_contract import ReplyGroundingPacket, ResolvedTemporalReference
from fitmas.plan_patch_backend_candidates import build_backend_candidate_refs_for_turn
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidate_reviewer import PlanPatchCandidateReviewDecision
from fitmas.plan_patch_candidates import PlanPatchCandidate, PlanPatchCandidateValidation
from fitmas.week_coherence import WeekCoherenceScore


def test_backend_move_candidate_refs_use_typed_temporal_refs_not_user_text() -> None:
    session = SimpleNamespace(
        id=42,
        scheduled_date=datetime.fromisoformat("2099-05-06"),
        sport_type="running",
        session_type="endurance",
        session_title="Footing endurance",
        duration_min=40,
        intensity="easy",
        priority="support",
        completion_status="planned",
    )
    grounding = ReplyGroundingPacket(
        local_date=date(2099, 5, 5),
        timezone_name="Europe/Paris",
        temporal_references={
            "source": (
                ResolvedTemporalReference(
                    role="source",
                    kind="relative_day",
                    value="tomorrow",
                    resolved_date=date(2099, 5, 6),
                    day_label="mercredi",
                ),
            ),
            "target": (
                ResolvedTemporalReference(
                    role="target",
                    kind="weekday",
                    value="friday",
                    resolved_date=date(2099, 5, 8),
                    day_label="vendredi",
                ),
            ),
        },
    )

    payloads, patches = build_backend_candidate_refs_for_turn(
        grounding=grounding,
        scheduled_sessions=[session],
    )

    assert {
        "candidate_ref": "backend:move_session:42:2099-05-08",
        "summary": "Déplacer Footing endurance du 2099-05-06 au 2099-05-08.",
        "operations": ["move_session"],
        "target_session_id": 42,
        "target_date": "2099-05-08",
    } in payloads
    patch = patches["backend:move_session:42:2099-05-08"]
    assert patch.operations[0].operation_type == "move_session"
    assert patch.operations[0].target_session_id == 42
    assert patch.operations[0].target_date == "2099-05-08"


def test_backend_candidate_refs_include_swap_lighten_and_replace_options() -> None:
    source = _session(
        session_id=42,
        scheduled_date="2099-05-06",
        sport_type="running",
        session_type="tempo",
        title="Fractionné seuil",
        duration_min=50,
        intensity="hard",
    )
    target = _session(
        session_id=43,
        scheduled_date="2099-05-08",
        sport_type="strength",
        session_type="general",
        title="Renfo général",
        duration_min=45,
        intensity="moderate",
    )
    grounding = ReplyGroundingPacket(
        local_date=date(2099, 5, 5),
        timezone_name="Europe/Paris",
        temporal_references={
            "source": (
                ResolvedTemporalReference(
                    role="source",
                    kind="relative_day",
                    value="tomorrow",
                    resolved_date=date(2099, 5, 6),
                    day_label="mercredi",
                ),
            ),
            "target": (
                ResolvedTemporalReference(
                    role="target",
                    kind="weekday",
                    value="friday",
                    resolved_date=date(2099, 5, 8),
                    day_label="vendredi",
                ),
            ),
        },
    )

    payloads, patches = build_backend_candidate_refs_for_turn(
        grounding=grounding,
        scheduled_sessions=[source, target],
    )
    refs = {payload["candidate_ref"] for payload in payloads}

    assert "backend:swap_sessions:42:43" in refs
    assert "backend:lighten_day:42:easy_30" in refs
    assert "backend:replace_session:42:recovery_30" in refs
    assert patches["backend:swap_sessions:42:43"].operations[0].operation_type == "swap_sessions"
    assert patches["backend:lighten_day:42:easy_30"].operations[0].operation_type == "lighten_day"
    replace_operation = patches["backend:replace_session:42:recovery_30"].operations[0]
    assert replace_operation.operation_type == "replace_session"
    assert replace_operation.new_sport_type == "mobility"
    assert replace_operation.new_session_type == "recovery"
    assert replace_operation.new_duration_min == 30


def test_backend_sport_unavailable_candidates_only_target_matching_sport() -> None:
    running = _session(
        session_id=42,
        scheduled_date="2099-05-06",
        sport_type="running",
        session_type="tempo",
        title="Fractionne seuil",
        duration_min=50,
        intensity="hard",
    )
    swimming_inside = _session(
        session_id=43,
        scheduled_date="2099-05-08",
        sport_type="swimming",
        session_type="easy",
        title="Natation souple",
        duration_min=45,
        intensity="easy",
    )
    swimming_later = _session(
        session_id=44,
        scheduled_date="2099-05-16",
        sport_type="swimming",
        session_type="endurance",
        title="Endurance piscine",
        duration_min=50,
        intensity="moderate",
    )
    swimming_outside = _session(
        session_id=45,
        scheduled_date="2099-05-25",
        sport_type="swimming",
        session_type="easy",
        title="Natation hors fenetre",
        duration_min=40,
        intensity="easy",
    )
    grounding = ReplyGroundingPacket(
        local_date=date(2099, 5, 5),
        timezone_name="Europe/Paris",
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=(),
        availability_constraint={
            "availability": "unavailable",
            "sport_type": "swimming",
            "starts_on": "2099-05-05",
            "ends_on": "2099-05-19",
        },
    )

    payloads, patches = build_backend_candidate_refs_for_turn(
        grounding=grounding,
        scheduled_sessions=[running, swimming_inside, swimming_later, swimming_outside],
        turn_plan=turn_plan,
    )
    target_ids = {payload["target_session_id"] for payload in payloads}

    assert target_ids == {43, 44}
    assert all(payload["constraint_sport_type"] == "swimming" for payload in payloads)
    assert all(payload["operations"] == ["replace_session"] for payload in payloads)
    assert all(operation.operation_type == "replace_session" for patch in patches.values() for operation in patch.operations)
    assert all(operation.new_sport_type != "swimming" for patch in patches.values() for operation in patch.operations)


def test_pending_choice_serialization_materializes_ref_candidates() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2099-05-08",
                rationale="Backend materialized move.",
            )
        ],
        coach_message="Candidate backend.",
    )
    evaluated = EvaluatedPlanPatchCandidate(
        candidate=PlanPatchCandidate(
            id="llm_candidate_1",
            patches=(),
            candidate_ref="backend:move_session:42:2099-05-08",
            rationale="Option backend.",
            expected_tradeoff="A confirmer.",
            confidence=0.8,
            assumptions=(),
            risk_notes=(),
            created_from_plan_id="plan_current",
            created_from_plan_version=1,
        ),
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=0,
            operation_count=0,
            operation_results=(),
            summary="Candidate ref valide.",
        ),
        patch=patch,
        patch_validation=None,
        week_context=None,
        facts=None,
        score=WeekCoherenceScore(
            total=80,
            recovery=80,
            goal_alignment=80,
            progression=80,
            adherence=80,
            readiness_fit=80,
            constraint_fit=80,
            risk=80,
        ),
        findings=(),
        score_delta=None,
        policy_hint="ask_confirmation",
        evaluation_summary="A confirmer.",
    )

    serialized = _pending_choice_serialization_candidates((evaluated,))

    assert serialized[0].patches == (patch,)
    assert serialized[0].candidate_ref is None


def test_adaptation_candidate_trace_includes_bounded_reviewer_decision() -> None:
    evaluated = _evaluated_ref_candidate()

    trace = _adaptation_candidate_trace(
        candidates=(evaluated.candidate,),
        evaluated=(evaluated,),
        policy_decision=AdaptationPolicyDecision(
            action="commit",
            selected_candidate_id="llm_candidate_1",
            candidate_options=(),
            reason="Option choisie par reviewer borne.",
            user_facing_reason="Option choisie par reviewer borne.",
            requires_confirmation_reason=None,
            risk_level="low",
        ),
        reviewer_decision=PlanPatchCandidateReviewDecision(
            preferred_candidate_id="llm_candidate_1",
            confidence=0.78,
            rationale=("Meilleur compromis humain.",),
        ),
    )

    assert trace["reviewer"] == {
        "preferred_candidate_id": "llm_candidate_1",
        "confidence": 0.78,
        "rationale": ["Meilleur compromis humain."],
    }


def _session(
    *,
    session_id: int,
    scheduled_date: str,
    sport_type: str,
    session_type: str,
    title: str,
    duration_min: int,
    intensity: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        scheduled_date=datetime.fromisoformat(scheduled_date),
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        duration_min=duration_min,
        intensity=intensity,
        priority="support",
        completion_status="planned",
    )


def _evaluated_ref_candidate() -> EvaluatedPlanPatchCandidate:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2099-05-08",
                rationale="Backend materialized move.",
            )
        ],
        coach_message="Candidate backend.",
    )
    return EvaluatedPlanPatchCandidate(
        candidate=PlanPatchCandidate(
            id="llm_candidate_1",
            patches=(),
            candidate_ref="backend:move_session:42:2099-05-08",
            rationale="Option backend.",
            expected_tradeoff="A confirmer.",
            confidence=0.8,
            assumptions=(),
            risk_notes=(),
            created_from_plan_id="plan_current",
            created_from_plan_version=1,
        ),
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=0,
            operation_count=0,
            operation_results=(),
            summary="Candidate ref valide.",
        ),
        patch=patch,
        patch_validation=None,
        week_context=None,
        facts=None,
        score=WeekCoherenceScore(
            total=80,
            recovery=80,
            goal_alignment=80,
            progression=80,
            adherence=80,
            readiness_fit=80,
            constraint_fit=80,
            risk=80,
        ),
        findings=(),
        score_delta=None,
        policy_hint="ask_confirmation",
        evaluation_summary="A confirmer.",
    )
