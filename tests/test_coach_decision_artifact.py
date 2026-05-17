from __future__ import annotations

import json
from types import SimpleNamespace

from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_from_raw,
    legacy_decision_artifact_json,
    legacy_decision_artifact_payload,
)


def test_artifact_from_raw_coach_decision_renames_visible_message_to_reply_hint() -> None:
    memory_action = SimpleNamespace(type="record_health_signal")
    execution_action = SimpleNamespace(type="record_execution_update")
    patch = SimpleNamespace(operations=())
    pending_resolution = SimpleNamespace(type="ignore")
    raw = SimpleNamespace(
        response_type="requires_confirmation",
        rationale="fatigue + semaine dense",
        fitmas_message="On allege ce soir.",
        confirmation_reason="Confirme si tu veux que je l'applique.",
        mutation_decision=None,
        plan_patch=patch,
        memory_actions=[memory_action],
        execution_actions=(execution_action,),
        pending_resolution=pending_resolution,
    )

    artifact = legacy_decision_artifact_from_raw(raw)

    assert artifact.kind == "coach_decision"
    assert artifact.is_coach_decision
    assert artifact.has_value
    assert artifact.response_type == "requires_confirmation"
    assert artifact.rationale == "fatigue + semaine dense"
    assert artifact.reply_hint == "On allege ce soir."
    assert artifact.confirmation_reason == "Confirme si tu veux que je l'applique."
    assert artifact.plan_patch is patch
    assert artifact.memory_actions == (memory_action,)
    assert artifact.execution_actions == (execution_action,)
    assert artifact.pending_resolution is pending_resolution

    payload = legacy_decision_artifact_payload(artifact)
    assert payload["reply_hint"] == "On allege ce soir."
    assert "fitmas_message" not in payload


def test_artifact_from_raw_legacy_readonly_decision() -> None:
    raw = SimpleNamespace(
        mutation_type="no_change",
        rationale="question simple",
        fitmas_message="On garde le plan.",
    )

    artifact = legacy_decision_artifact_from_raw(raw)

    assert artifact.kind == "legacy_readonly"
    assert artifact.is_legacy_readonly
    assert artifact.has_value
    assert artifact.response_type == "no_change"
    assert artifact.rationale == "question simple"
    assert artifact.reply_hint == "On garde le plan."


def test_artifact_from_raw_mutating_legacy_decision_is_unsupported_but_traceable() -> None:
    raw = SimpleNamespace(
        mutation_type="move_session",
        rationale="ancien chemin mutation",
        fitmas_message="Je deplace.",
    )

    artifact = legacy_decision_artifact_from_raw(raw)

    assert artifact.kind == "unsupported"
    assert not artifact.has_value
    assert artifact.response_type == "mutation_decision"
    assert artifact.mutation_type == "move_session"
    assert artifact.mutation_decision is raw
    assert artifact.reply_hint == "Je deplace."


def test_artifact_from_none_and_unknown_are_non_values() -> None:
    none_artifact = legacy_decision_artifact_from_raw(None)
    unsupported = legacy_decision_artifact_from_raw(SimpleNamespace(foo="bar"))

    assert none_artifact.kind == "none"
    assert not none_artifact.has_value
    assert unsupported.kind == "unsupported"
    assert not unsupported.has_value


def test_artifact_json_serializes_machine_payload_without_raw_message_name() -> None:
    artifact = LegacyCoachDecisionArtifact(
        kind="coach_decision",
        response_type="reply",
        rationale="ok",
        reply_hint="Bien recu.",
        memory_actions=(SimpleNamespace(type="record_preference"),),
    )

    payload = json.loads(legacy_decision_artifact_json(artifact))

    assert payload["kind"] == "coach_decision"
    assert payload["reply_hint"] == "Bien recu."
    assert payload["memory_action_count"] == 1
    assert "fitmas_message" not in payload
