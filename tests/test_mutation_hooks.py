from __future__ import annotations

from fitmas.llm import MutationDecision
from fitmas.mutation_hooks import run_pre_mutation_hooks


def test_move_session_blocks_same_sport_proximity_under_48h() -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-15",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "running",
            "session_type": "tempo",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-16",
            "sport_type": "running",
            "session_type": "tempo",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is False
    assert result.block_reason == "same_sport_proximity"


def test_move_session_allows_different_sport_proximity() -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-15",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "running",
            "session_type": "tempo",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-16",
            "sport_type": "swimming",
            "session_type": "tempo",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_move_session_allows_stable_recovery_target() -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-15",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "running",
            "session_type": "tempo",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos protecteur",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_move_session_allows_flexible_recovery_target() -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-15",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "running",
            "session_type": "tempo",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Journee flexible",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_swap_sessions_allows_stable_recovery_target() -> None:
    """Sport coherence: a swap never destroys a recovery — it just moves
    it. Whether the recovery is flagged `stable` or `flexible`, the swap
    preserves both sessions in the week, so we allow it.

    The destructive mutations (replace/update/lighten) still block on
    stable recovery because they erase it in place."""
    decision = MutationDecision(
        mutation_type="swap_sessions",
        target_session_id=10,
        second_session_id=11,
        rationale="swap",
        fitmas_message="Je swap.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "swimming",
            "session_type": "css",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos stable",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_swap_sessions_allows_flexible_recovery_target() -> None:
    """A swap between a training and a flexible recovery is allowed —
    the recovery migrates, it does not disappear."""
    decision = MutationDecision(
        mutation_type="swap_sessions",
        target_session_id=10,
        second_session_id=11,
        rationale="swap",
        fitmas_message="Je swap.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "swimming",
            "session_type": "css",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Journee flexible",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_replace_session_allows_stable_recovery() -> None:
    """A stable recovery is part of the plan, not a writer-level lock.

    Week coherence review owns the sporting trade-off.
    """
    decision = MutationDecision(
        mutation_type="replace_session",
        target_session_id=11,
        rationale="remplacer",
        fitmas_message="Je remplace.",
    )
    sessions = [
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos protecteur",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_replace_session_allows_flexible_recovery() -> None:
    """Replacing a flexible recovery is allowed — the user can take back
    a rest day that wasn't protected."""
    decision = MutationDecision(
        mutation_type="replace_session",
        target_session_id=11,
        rationale="remplacer",
        fitmas_message="Je remplace.",
    )
    sessions = [
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Journee flexible",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_update_session_allows_stable_recovery() -> None:
    """Stable recovery is not a hard runtime lock."""
    decision = MutationDecision(
        mutation_type="update_session",
        target_session_id=11,
        rationale="update",
        fitmas_message="Je mets a jour.",
    )
    sessions = [
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos protecteur",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_lighten_day_allows_stable_recovery() -> None:
    """Recovery coherence belongs to review, not pre-hook hard-blocking."""
    decision = MutationDecision(
        mutation_type="lighten_day",
        target_session_id=11,
        rationale="allege",
        fitmas_message="J'allege.",
    )
    sessions = [
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos protecteur",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is True
    assert result.block_reason is None


def test_move_session_blocks_occupied_training_target() -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-15",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )
    sessions = [
        {
            "id": 10,
            "scheduled_date": "2026-04-13",
            "sport_type": "strength",
            "session_type": "general",
            "completion_status": "planned",
        },
        {
            "id": 11,
            "scheduled_date": "2026-04-15",
            "sport_type": "running",
            "session_type": "endurance",
            "session_title": "Footing endurance",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    result = run_pre_mutation_hooks(
        object(),
        plan_id=42,
        decision=decision,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert result.allowed is False
    assert result.block_reason == "occupied_training_target"
