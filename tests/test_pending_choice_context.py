from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from fitmas.conversation_pipeline import _pending_confirmation_context_for_prompt


def test_pending_choice_context_instructs_llm_to_select_candidate_id() -> None:
    pending = SimpleNamespace(
        id=9,
        mutation_type="plan_patch_choice",
        reason="Deux options proches.",
        summary="move_friday | reduce_tomorrow",
        decision_json=(
            '{"kind":"plan_patch_choice","candidates":['
            '{"id":"move_friday","patches":[]},'
            '{"id":"reduce_tomorrow","patches":[]}'
            "]}"
        ),
        expires_at=datetime.now() + timedelta(minutes=10),
    )

    context = _pending_confirmation_context_for_prompt(pending)

    assert context is not None
    assert "plan_patch_choice" in context
    assert "selected_candidate_id" in context
    assert "move_friday" in context
    assert "reduce_tomorrow" in context
