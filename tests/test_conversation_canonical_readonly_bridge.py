from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal
from fitmas.legacy import conversation_canonical_readonly_bridge as bridge


def _understanding(
    intent: str = "plan_lookup",
    *,
    requested_change=None,
    pending_resolution=None,
    signals=(),
) -> CoachUnderstanding:
    return CoachUnderstanding(
        intent=intent,
        confidence=0.9,
        user_summary="Demande de lecture du plan.",
        extracted_signals=tuple(signals),
        requested_change=requested_change,
        pending_resolution=pending_resolution,
        clarification_need=None,
    )


def test_readonly_provider_flag_defaults_on_after_8s(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    assert bridge.canonical_readonly_provider_enabled() is True


def test_readonly_provider_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_READONLY_PROVIDER", "0")

    assert bridge.canonical_readonly_provider_enabled() is False


def test_readonly_gate_accepts_plan_lookup_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    assert bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding("plan_lookup"),
        turn_plan=SimpleNamespace(
            primary_intent="plan_lookup",
            secondary_intents=(),
            requires_truth_read=True,
            truth_scope="plan_window",
        ),
        pending_confirmation=None,
    )


def test_readonly_gate_rejects_planning(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding(
            "plan_change",
            requested_change=RequestedPlanChange(
                kind="move",
                source_ref="demain",
                target_ref="vendredi",
                desired_sport=None,
                desired_duration_min=None,
                desired_intensity=None,
                reason="demande user",
                risk_signals=(),
            ),
        ),
        turn_plan=SimpleNamespace(primary_intent="plan_mutation", secondary_intents=()),
        pending_confirmation=None,
    )


def test_readonly_gate_rejects_active_pending(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding(
            "pending_response",
            pending_resolution=PendingResolution(
                type="accept_pending",
                reason="ok",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            ),
        ),
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=()),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_readonly_gate_rejects_command_signals(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)

    signal = UserSignal(
        type="availability",
        label="piscine fermee",
        status="unavailable",
        severity="unknown",
        confidence=0.9,
        evidence="piscine fermee",
        payload={
            "action_type": "record_availability",
            "availability": "unavailable",
            "sport_type": "swimming",
        },
    )

    assert not bridge.should_use_canonical_readonly_without_legacy(
        understanding=_understanding("availability_signal", signals=(signal,)),
        turn_plan=SimpleNamespace(primary_intent="availability_constraint", secondary_intents=()),
        pending_confirmation=None,
    )


class FakeComposer:
    def compose(self, outcome, context, *, user_text="", grounding_facts=()):
        assert outcome.kind == "answer"
        assert context is None
        assert user_text == "c'est quoi demain ?"
        assert outcome.commands == ()
        assert outcome.applied_commands == ()
        assert "mutation_committed" not in outcome.reply_contract.allowed_claims
        assert "plan_changed" in outcome.reply_contract.forbidden_claims
        assert grounding_facts == ("Demain: endurance 45min",)
        return SimpleNamespace(
            text="Demain, endurance 45 minutes.",
            verified=True,
            fallback_used=False,
            reason=None,
        )


def test_compose_canonical_readonly_outcome_returns_conversation_outcome(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_READONLY_PROVIDER", raising=False)
    turn_context: dict[str, object] = {}

    outcome = bridge.compose_canonical_readonly_reply(
        composer=FakeComposer(),
        understanding=_understanding("plan_lookup"),
        user_text="c'est quoi demain ?",
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=()),
        turn_context=turn_context,
        grounding_facts=("Demain: endurance 45min",),
    )

    assert outcome is not None
    assert outcome.reply_text == "Demain, endurance 45 minutes."
    assert outcome.response_mode == "canonical_readonly_answer"
    assert outcome.mutation_applied is False
    assert turn_context["legacy_decide"]["legacy_skipped"] is True
    assert turn_context["canonical_readonly_reply"]["source"] == "coach_understanding"
