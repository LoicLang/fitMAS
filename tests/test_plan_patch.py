from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.legacy.domain.planning.plan_patch import (
    PlanPatch,
    PlanPatchOperation,
    adapt_plan_patch_to_mutation_decisions,
    validate_plan_patch,
)


def test_plan_patch_adapts_ordered_batch_to_legacy_mutation_decisions() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="easy",
                new_title="Running relais",
                new_duration_min=40,
                new_intensity="easy",
                rationale="Piscine fermee.",
            ),
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=23,
                target_date="2026-04-25",
                rationale="Garder une recuperation avant la seance dure.",
            ),
        ],
        coach_message="Je remplace la nage et je decale la suite.",
    )

    decisions = adapt_plan_patch_to_mutation_decisions(patch)

    assert [decision.mutation_type for decision in decisions] == ["replace_session", "move_session"]
    assert decisions[0].target_session_id == 22
    assert decisions[0].new_sport_type == "running"
    assert decisions[0].fitmas_message == patch.coach_message
    assert decisions[1].target_session_id == 23
    assert decisions[1].target_date == "2026-04-25"
    assert decisions[1].fitmas_message == patch.coach_message


def test_plan_patch_adaptation_skips_create_session_operations() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="create_session",
                target_date="2099-04-29",
                new_sport_type="running",
                new_title="Footing easy",
                new_duration_min=30,
                rationale="Ajouter une seance.",
            )
        ],
        coach_message="Je pose un footing.",
    )

    assert adapt_plan_patch_to_mutation_decisions(patch) == []


def test_plan_patch_validation_requires_confirmation_for_training_warnings() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="tempo",
                new_title="Tempo relais",
                new_duration_min=45,
                new_intensity="hard",
                rationale="Remplacer la nage par une course qualite.",
            )
        ],
        coach_message="Je mets un tempo a la place.",
    )
    sessions = [
        SimpleNamespace(id=20, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=21, intensity="key", completion_status="planned"),
        SimpleNamespace(id=24, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=22, intensity="easy", completion_status="planned"),
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "requires_confirmation"
    assert validation.operation_results[0].status == "requires_confirmation"
    assert validation.operation_results[0].warning_codes == ("hard_session_limit",)


def test_plan_patch_validation_requires_confirmation_when_replacing_key_session_sport() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="swimming",
                new_session_type="easy",
                new_title="Natation souple",
                new_duration_min=35,
                new_intensity="easy",
                rationale="Remplacer la seance cle par moins d'impact.",
            )
        ],
        coach_message="Je remplace par natation souple.",
    )
    sessions = [
        SimpleNamespace(
            id=22,
            sport_type="running",
            session_title="Tempo 10k",
            priority="Seance cle",
            intensity="hard",
            completion_status="planned",
        ),
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "requires_confirmation"
    result = validation.operation_results[0]
    assert result.status == "requires_confirmation"
    assert result.warning_codes == ("replace_key_session_changes_sport",)
    assert "confirmation" in str(result.suggested_fix).lower()


def test_plan_patch_validation_blocks_impossible_operations() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=10,
                target_date="2026-04-15",
                rationale="Deplacer le tempo.",
            )
        ],
        coach_message="Je deplace.",
    )
    sessions = [
        SimpleNamespace(
            id=10,
            scheduled_date=date(2026, 4, 13),
            sport_type="running",
            session_type="tempo",
            completion_status="planned",
        ),
        SimpleNamespace(
            id=11,
            scheduled_date=date(2026, 4, 16),
            sport_type="running",
            session_type="tempo",
            completion_status="planned",
        ),
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "blocked"
    assert validation.operation_results[0].status == "blocked"
    assert validation.operation_results[0].block_reason == "same_sport_proximity"
    assert validation.operation_results[0].suggested_fix == "Choisir une date a plus de 48h de l'autre running/tempo."
    assert validation.summary == "Patch bloque: move_session same_sport_proximity."


def test_plan_patch_validation_requires_confirmation_for_ambiguous_same_sport_move_target() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=10,
                target_date="2099-04-18",
                rationale="Deplacer la course a vendredi.",
            )
        ],
        coach_message="Je deplace la course a vendredi.",
    )
    sessions = [
        SimpleNamespace(
            id=10,
            scheduled_date=date(2099, 4, 14),
            sport_type="running",
            session_type="easy",
            completion_status="planned",
        ),
        SimpleNamespace(
            id=11,
            scheduled_date=date(2099, 4, 16),
            sport_type="running",
            session_type="tempo",
            completion_status="planned",
        ),
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "requires_confirmation"
    result = validation.operation_results[0]
    assert result.status == "requires_confirmation"
    assert result.warning_codes == ("ambiguous_target_reference",)
    assert "confirmation" in str(result.suggested_fix).lower()


def test_plan_patch_validation_blocks_missing_target_session_before_commit() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=999,
                new_sport_type="running",
                new_session_type="easy",
                new_title="Footing easy",
                new_duration_min=35,
                new_intensity="easy",
                rationale="Remplacer une ancienne natation.",
            )
        ],
        coach_message="Je remplace.",
    )
    sessions = [
        SimpleNamespace(
            id=10,
            scheduled_date=date(2026, 4, 22),
            sport_type="running",
            session_type="easy",
            completion_status="planned",
        )
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "blocked"
    assert validation.operation_results[0].block_reason == "target_session_not_found"
    assert validation.operation_results[0].suggested_fix == "Relire le planning actuel et cibler une session active."


def test_plan_patch_validation_blocks_completed_session_target() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="lighten_day",
                target_session_id=22,
                rationale="Alleger une seance deja resolue.",
            )
        ],
        coach_message="J'allege.",
    )
    sessions = [
        SimpleNamespace(
            id=22,
            scheduled_date=date(2026, 4, 22),
            sport_type="strength",
            session_type="strength",
            completion_status="skipped",
        )
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "blocked"
    assert validation.operation_results[0].block_reason == "completed_session_target"
    assert validation.operation_results[0].suggested_fix == (
        "Cibler une seance encore planifiee; ne pas modifier une seance deja faite ou skippee."
    )


def test_plan_patch_validation_allows_move_to_stable_recovery() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=10,
                target_date="2099-04-15",
                rationale="Deplacer le tempo sur le jour de repos.",
            )
        ],
        coach_message="Je deplace.",
    )
    sessions = [
        SimpleNamespace(
            id=10,
            scheduled_date=date(2099, 4, 13),
            sport_type="running",
            session_type="tempo",
            completion_status="planned",
        ),
        SimpleNamespace(
            id=11,
            scheduled_date=date(2099, 4, 15),
            sport_type="rest",
            session_type="rest",
            session_title="Repos protecteur",
            flexibility="stable",
            completion_status="planned",
        ),
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "valid"
    assert validation.operation_results[0].block_reason is None
    assert validation.operation_results[0].suggested_fix is None


def test_plan_patch_validation_accepts_low_risk_create_session() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="create_session",
                target_date="2099-04-29",
                new_sport_type="running",
                new_session_type="easy",
                new_title="Footing easy",
                new_goal="Garder du volume sans piscine.",
                new_duration_min=30,
                new_intensity="easy",
                rationale="Piscine fermee, remplacement leger.",
            )
        ],
        coach_message="Je pose un footing easy mercredi.",
    )

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=[],
        timezone_name="Europe/Paris",
    )

    assert validation.status == "valid"
    assert validation.operation_results[0].operation_type == "create_session"


def test_plan_patch_validation_blocks_create_session_on_occupied_training_day() -> None:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="create_session",
                target_date="2099-04-29",
                new_sport_type="running",
                new_title="Footing easy",
                new_duration_min=30,
                rationale="Ajouter un footing.",
            )
        ],
        coach_message="Je pose un footing.",
    )
    sessions = [
        SimpleNamespace(
            id=42,
            scheduled_date=date(2099, 4, 29),
            sport_type="running",
            session_type="tempo",
            flexibility="stable",
            completion_status="planned",
        )
    ]

    validation = validate_plan_patch(
        object(),
        plan_id=0,
        patch=patch,
        scheduled_sessions=sessions,
        timezone_name="Europe/Paris",
    )

    assert validation.status == "blocked"
    assert validation.operation_results[0].block_reason == "occupied_training_target"
