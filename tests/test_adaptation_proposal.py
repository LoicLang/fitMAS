from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from fitmas.adaptation_proposal import (
    AdaptationProposal,
    AdaptationProposalOperation,
    compile_adaptation_proposal,
    generate_adaptation_proposal,
)
from fitmas.planning_snapshot import build_planning_snapshot_from_records


def _session(session_id: int, day: date, sport: str):
    return SimpleNamespace(
        id=session_id,
        scheduled_date=datetime.combine(day, datetime.min.time()),
        sport_type=sport,
        session_type="easy",
        session_title=f"{sport} easy",
        session_goal="tenir la regularite",
        session_note="",
        session_description="40 min facile",
        duration_min=40,
        intensity="easy",
        load_score=1,
        priority="Normal",
        flexibility="stable",
        completion_status="planned",
    )


def _snapshot():
    return build_planning_snapshot_from_records(
        user_id=1,
        timezone_name="Europe/Paris",
        start_date=date(2026, 5, 13),
        end_date=date(2026, 5, 17),
        sessions=[
            _session(13, date(2026, 5, 13), "running"),
            _session(14, date(2026, 5, 14), "swimming"),
            SimpleNamespace(
                id=16,
                scheduled_date=datetime(2026, 5, 16),
                sport_type="rest",
                session_type="rest",
                session_title="Repos total",
                session_goal="",
                session_note="",
                session_description="",
                duration_min=None,
                intensity="easy",
                load_score=0,
                priority="Normal",
                flexibility="stable",
                completion_status="planned",
            ),
        ],
        memory_rows=[],
        now=datetime(2026, 5, 13, 12, 0),
    )


def test_compiles_move_operations_from_snapshot_refs() -> None:
    proposal = AdaptationProposal(
        response_type="adaptation_proposal",
        summary="running demain, piscine vendredi, repos samedi preserve",
        operations=[
            AdaptationProposalOperation(
                op="move",
                source_ref="session:13",
                target_date="2026-05-14",
                reason="courbatures aujourd'hui, demain disponible",
            ),
            AdaptationProposalOperation(
                op="move",
                source_ref="session:14",
                target_date="2026-05-15",
                reason="liberer jeudi pour courir",
            ),
            AdaptationProposalOperation(
                op="keep",
                source_ref="session:16",
                reason="preserver le repos total",
            ),
        ],
        requires_confirmation=True,
        confidence=0.82,
    )

    result = compile_adaptation_proposal(proposal, snapshot=_snapshot())

    assert result.ok is True
    assert result.patch is not None
    assert [operation.operation_type for operation in result.patch.operations] == ["swap_sessions", "move_session"]
    assert result.patch.operations[0].target_session_id == 13
    assert result.patch.operations[0].second_session_id == 14
    assert result.patch.operations[1].target_session_id == 14
    assert result.patch.operations[1].target_date == "2026-05-15"
    assert result.patch.confirmation_reason == "running demain, piscine vendredi, repos samedi preserve"


def test_blocks_unknown_snapshot_ref_without_guessing() -> None:
    proposal = AdaptationProposal(
        response_type="adaptation_proposal",
        summary="bouger une seance absente",
        operations=[
            AdaptationProposalOperation(
                op="move",
                source_ref="session:999",
                target_date="2026-05-14",
                reason="ref inexistante",
            ),
        ],
        requires_confirmation=True,
        confidence=0.5,
    )

    result = compile_adaptation_proposal(proposal, snapshot=_snapshot())

    assert result.ok is False
    assert result.patch is None
    assert result.errors == ("UNKNOWN_REF:session:999",)


def test_compiler_skips_unscored_recovery_move_without_blocking_primary_ops() -> None:
    snapshot = build_planning_snapshot_from_records(
        user_id=1,
        timezone_name="Europe/Paris",
        start_date=date(2026, 5, 13),
        end_date=date(2026, 5, 17),
        sessions=[
            _session(13, date(2026, 5, 13), "running"),
            _session(14, date(2026, 5, 14), "swimming"),
            SimpleNamespace(
                id=15,
                scheduled_date=datetime(2026, 5, 15),
                sport_type="rest",
                session_type="rest",
                session_title="Repos actif",
                session_goal="Mobilite",
                session_note="",
                session_description="20 min mobilite",
                duration_min=20,
                intensity="easy",
                load_score=0,
                priority="Normal",
                flexibility="stable",
                completion_status="planned",
            ),
        ],
        memory_rows=[],
        now=datetime(2026, 5, 13, 12, 0),
    )
    proposal = AdaptationProposal(
        response_type="adaptation_proposal",
        summary="running demain, piscine vendredi, recovery preservee",
        operations=[
            AdaptationProposalOperation(
                op="move",
                source_ref="session:13",
                target_date="2026-05-14",
                reason="running demain",
            ),
            AdaptationProposalOperation(
                op="move",
                source_ref="session:14",
                target_date="2026-05-15",
                reason="piscine vendredi",
            ),
            AdaptationProposalOperation(
                op="move",
                source_ref="session:15",
                target_date="2026-05-13",
                reason="replacer la recovery",
            ),
        ],
        requires_confirmation=True,
        confidence=0.86,
    )

    result = compile_adaptation_proposal(proposal, snapshot=snapshot)

    assert result.ok is True
    assert result.patch is not None
    assert [operation.target_session_id for operation in result.patch.operations] == [13, 14]


def test_compiler_rewrites_move_chain_through_occupied_day_as_swap_then_move() -> None:
    proposal = AdaptationProposal(
        response_type="adaptation_proposal",
        summary="running demain, piscine vendredi",
        operations=[
            AdaptationProposalOperation(
                op="move",
                source_ref="session:13",
                target_date="2026-05-14",
                reason="running demain",
            ),
            AdaptationProposalOperation(
                op="move",
                source_ref="session:14",
                target_date="2026-05-15",
                reason="piscine vendredi",
            ),
        ],
        requires_confirmation=True,
        confidence=0.9,
    )

    result = compile_adaptation_proposal(proposal, snapshot=_snapshot())

    assert result.ok is True
    assert result.patch is not None
    assert [operation.operation_type for operation in result.patch.operations] == ["swap_sessions", "move_session"]
    assert result.patch.operations[0].target_session_id == 13
    assert result.patch.operations[0].second_session_id == 14
    assert result.patch.operations[1].target_session_id == 14
    assert result.patch.operations[1].target_date == "2026-05-15"


def test_compiler_rewrites_single_move_to_occupied_day_as_swap() -> None:
    proposal = AdaptationProposal(
        response_type="adaptation_proposal",
        summary="running demain en echangeant avec la piscine",
        operations=[
            AdaptationProposalOperation(
                op="move",
                source_ref="session:13",
                target_date="2026-05-14",
                reason="demain est meilleur pour courir",
            ),
        ],
        requires_confirmation=True,
        confidence=0.84,
    )

    result = compile_adaptation_proposal(proposal, snapshot=_snapshot())

    assert result.ok is True
    assert result.patch is not None
    assert [operation.operation_type for operation in result.patch.operations] == ["swap_sessions"]
    assert result.patch.operations[0].target_session_id == 13
    assert result.patch.operations[0].second_session_id == 14


def test_generate_adaptation_proposal_parses_json_only_payload() -> None:
    calls = []

    def fake_request_json_fn(**kwargs):
        calls.append(kwargs)
        return {
            "response_type": "adaptation_proposal",
            "summary": "running demain, piscine vendredi",
            "operations": [
                {
                    "op": "move",
                    "source_ref": "session:13",
                    "target_date": "2026-05-14",
                    "reason": "demain dispo",
                }
            ],
            "requires_confirmation": True,
            "confidence": 0.84,
        }

    proposal = generate_adaptation_proposal(
        user_message="Dans ce cas running demain et piscine vendredi ?",
        parsed_user_intent={"primary_intent": "plan_mutation"},
        snapshot=_snapshot(),
        request_json_fn=fake_request_json_fn,
    )

    assert proposal is not None
    assert proposal.operations[0].source_ref == "session:13"
    assert "PlanningSnapshot" in calls[0]["system"]
    assert "session:13" in calls[0]["prompt"]


def test_generate_adaptation_proposal_can_pin_model_for_bounded_compiler() -> None:
    calls = []

    def fake_request_json_fn(**kwargs):
        calls.append(kwargs)
        return {
            "response_type": "adaptation_proposal",
            "operations": [
                {
                    "op": "move",
                    "source_ref": "session:13",
                    "target_date": "2026-05-14",
                    "reason": "running tomorrow",
                }
            ],
            "requires_confirmation": True,
            "confidence": 0.84,
        }

    proposal = generate_adaptation_proposal(
        user_message="Dans ce cas running demain ?",
        parsed_user_intent={"primary_intent": "plan_mutation"},
        snapshot=_snapshot(),
        request_json_fn=fake_request_json_fn,
        model="deepseek-v4-flash",
    )

    assert proposal is not None
    assert calls[0]["model"] == "deepseek-v4-flash"


def test_generate_adaptation_proposal_accepts_missing_summary_when_operations_exist() -> None:
    def fake_request_json_fn(**kwargs):
        return {
            "response_type": "adaptation_proposal",
            "operations": [
                {
                    "op": "move",
                    "source_ref": "session:13",
                    "target_date": "2026-05-14",
                    "reason": "running tomorrow",
                }
            ],
            "requires_confirmation": True,
            "confidence": 0.84,
        }

    proposal = generate_adaptation_proposal(
        user_message="Dans ce cas running demain ?",
        parsed_user_intent={"primary_intent": "plan_mutation"},
        snapshot=_snapshot(),
        request_json_fn=fake_request_json_fn,
    )

    assert proposal is not None
    assert proposal.summary == "running tomorrow"
