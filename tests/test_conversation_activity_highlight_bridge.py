from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fitmas.legacy import conversation_activity_highlight_bridge as bridge


def test_activity_highlight_bridge_composes_duration_highlight_without_legacy() -> None:
    activities = (
        SimpleNamespace(
            title="Footing controle",
            sport_type="running",
            duration_min=45,
            distance_m=0,
            avg_speed=None,
            started_at=datetime(2026, 5, 16, 8, 0),
        ),
        SimpleNamespace(
            title="Endurance velo",
            sport_type="cycling",
            duration_min=70,
            distance_m=0,
            avg_speed=None,
            started_at=datetime(2026, 5, 13, 8, 0),
        ),
    )
    turn_plan = SimpleNamespace(
        primary_intent="activity_highlights",
        secondary_intents=(),
        confidence=0.86,
    )

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "answer"
            assert outcome.reply_contract.mode == "canonical_activity_highlight"
            return SimpleNamespace(text=outcome.explanation.reason_summary, verified=True)

    turn_context: dict[str, object] = {}

    outcome = bridge.compose_activity_highlight_reply(
        composer=FakeComposer(),
        activities=activities,
        user_text="C'etait quoi ma plus longue sortie recente ?",
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=(),
    )

    assert outcome is not None
    assert outcome.response_mode == "canonical_activity_highlight"
    assert "Endurance velo" in outcome.reply_text
    assert "70 min" in outcome.reply_text
    assert turn_context["legacy_decide"]["legacy_skipped"] is True


def test_activity_highlight_bridge_ignores_non_highlight_turn() -> None:
    outcome = bridge.compose_activity_highlight_reply(
        composer=SimpleNamespace(),
        activities=(),
        user_text="Redonne le plan",
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=()),
        turn_context={},
        grounding_facts=(),
    )

    assert outcome is None
