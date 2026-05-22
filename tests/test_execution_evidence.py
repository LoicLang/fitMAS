from fitmas.domain.execution.claims import ActivityClaim
from fitmas.domain.execution.evidence import classify_execution_evidence


def test_same_sport_activity_without_link_stays_uncertain() -> None:
    evidence = classify_execution_evidence(
        planned_session={
            "id": 12,
            "sport_type": "running",
            "completion_status": "planned",
        },
        activities=[
            {
                "id": 71,
                "sport_type": "running",
                "scheduled_session_id": None,
            }
        ],
    )

    assert evidence.evidence_state == "candidate"
    assert evidence.plan_relation == "same_sport"
    assert evidence.display_status == "uncertain"
    assert evidence.activity_id == 71


def test_marked_done_without_activity_stays_uncertain() -> None:
    evidence = classify_execution_evidence(
        planned_session={
            "id": 12,
            "sport_type": "running",
            "completion_status": "done",
        },
        activities=[],
    )

    assert evidence.evidence_state == "none"
    assert evidence.display_status == "uncertain"
    assert "sans activite" in evidence.reason.lower()


def test_claimed_same_sport_activity_stays_claimed_done() -> None:
    evidence = classify_execution_evidence(
        planned_session={
            "id": 12,
            "sport_type": "running",
            "completion_status": "planned",
        },
        claims=[
            ActivityClaim(
                sport_type="running",
                duration_min=30,
                resolved_date_iso="2026-03-22",
                temporal_reference="yesterday",
                confidence=0.8,
                source_text="j'ai couru hier",
            )
        ],
    )
    assert evidence.display_status == "claimed_done"
    assert evidence.evidence_state == "claimed"
