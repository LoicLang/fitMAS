from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import fitmas.heartbeat as heartbeat
from fitmas.skills.heartbeat import tool_loop
from fitmas.tool_contract import ToolContext
from fitmas.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


class HeartbeatToolLoopTest(unittest.TestCase):
    def test_llm_generate_executes_heartbeat_read_tool_before_final_reply(self) -> None:
        requests: list[dict] = []
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="get_plan_window",
                        input={"start_date": "2026-05-04", "end_date": "2026-05-05"},
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Je garde juste un oeil: demain reste leger.")],
            ),
        ]

        def fake_request_message(**kwargs):
            requests.append(kwargs)
            return responses.pop(0)

        context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T07:30:00+02:00"),
            scheduled_sessions=[
                {
                    "id": 10,
                    "scheduled_date": "2026-05-05T07:00:00+02:00",
                    "sport_type": "running",
                    "session_title": "Footing facile",
                    "duration_min": 35,
                    "completion_status": "planned",
                }
            ],
        )

        original_request_message = tool_loop.gw.request_message
        original_request_text = heartbeat.request_text
        try:
            tool_loop.gw.request_message = fake_request_message
            heartbeat.request_text = lambda **_kwargs: "ALLOW"
            with heartbeat.capture_debug_trace("morning") as trace:
                text = heartbeat._llm_generate(
                    "system",
                    "prompt",
                    pipeline="heartbeat_briefing",
                    tool_context=context,
                )
        finally:
            tool_loop.gw.request_message = original_request_message
            heartbeat.request_text = original_request_text

        self.assertEqual(text, "Je garde juste un oeil: demain reste leger.")
        self.assertEqual(len(requests), 2)
        self.assertIn("tools", requests[0])
        self.assertEqual(requests[0]["tool_choice"], {"type": "auto"})
        followup_content = requests[1]["messages"][-1]["content"]
        self.assertEqual(followup_content[0]["type"], "tool_result")
        self.assertEqual(followup_content[0]["tool_use_id"], "toolu_1")
        self.assertIn("Footing facile", followup_content[0]["content"])
        self.assertIn("get_plan_window", trace.tools["offered"])
        self.assertIn("get_recent_activities", trace.tools["offered"])
        self.assertEqual(trace.tools["requested"], ["get_plan_window"])
        self.assertEqual(trace.tools["results"][0]["status"], "ok")

    def test_llm_generate_captures_validated_plan_patch_as_pending_candidate(self) -> None:
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="validate_plan_patch",
                        input={
                            "patch": {
                                "coach_message": "Je te propose d'alleger demain.",
                                "operations": [
                                    {
                                        "operation_type": "lighten_day",
                                        "target_session_id": 10,
                                        "rationale": "Charge haute.",
                                    }
                                ],
                            }
                        },
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Je te propose d'alleger demain — tu confirmes ?")],
            ),
        ]

        def fake_request_message(**_kwargs):
            return responses.pop(0)

        context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T07:30:00+02:00"),
            scheduled_sessions=[
                {
                    "id": 10,
                    "scheduled_date": "2026-05-05T07:00:00+02:00",
                    "sport_type": "running",
                    "session_title": "Footing facile",
                    "duration_min": 35,
                    "completion_status": "planned",
                }
            ],
        )

        original_request_message = tool_loop.gw.request_message
        original_request_text = heartbeat.request_text
        try:
            tool_loop.gw.request_message = fake_request_message
            heartbeat.request_text = lambda **_kwargs: "ALLOW"
            text = heartbeat._llm_generate(
                "system",
                "prompt",
                pipeline="heartbeat_signal",
                tool_context=context,
            )
            pending = heartbeat._take_pending_confirmation()
        finally:
            tool_loop.gw.request_message = original_request_message
            heartbeat.request_text = original_request_text

        self.assertEqual(text, "Je te propose d'alleger demain — tu confirmes ?")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "plan_patch")
        self.assertIn('"kind": "plan_patch"', pending.decision_json)
        self.assertIn("lighten_day", pending.decision_json)

    def test_llm_generate_captures_week_reviewed_plan_patch_as_pending_candidate(self) -> None:
        patch_payload = {
            "coach_message": "Je te propose d'alleger demain.",
            "operations": [
                {
                    "operation_type": "lighten_day",
                    "target_session_id": 10,
                    "rationale": "Charge haute.",
                }
            ],
        }
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="validate_week_coherence",
                        input={"patch": patch_payload},
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Je te propose d'alleger demain — tu confirmes ?")],
            ),
        ]

        def fake_request_message(**_kwargs):
            return responses.pop(0)

        context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T07:30:00+02:00"),
            scheduled_sessions=[
                {
                    "id": 10,
                    "scheduled_date": "2026-05-05T07:00:00+02:00",
                    "sport_type": "running",
                    "session_title": "Footing facile",
                    "duration_min": 35,
                    "completion_status": "planned",
                }
            ],
        )
        review = WeekCoherenceReview(
            status="requires_confirmation",
            sport_quality="fragile",
            confidence=0.8,
            summary="Allegement acceptable mais a confirmer.",
            findings=(
                WeekCoherenceFinding(
                    code="health_constraint_requires_review",
                    severity="requires_confirmation",
                    detail="Charge haute.",
                ),
            ),
            suggested_adjustments=(),
            recommended_policy="confirm_original",
        )

        original_request_message = tool_loop.gw.request_message
        original_request_text = heartbeat.request_text
        try:
            tool_loop.gw.request_message = fake_request_message
            heartbeat.request_text = lambda **_kwargs: "ALLOW"
            with patch("fitmas.tools.registry.review_week_coherence_with_llm", return_value=review, create=True):
                text = heartbeat._llm_generate(
                    "system",
                    "prompt",
                    pipeline="heartbeat_signal",
                    tool_context=context,
                )
                pending = heartbeat._take_pending_confirmation()
        finally:
            tool_loop.gw.request_message = original_request_message
            heartbeat.request_text = original_request_text

        self.assertEqual(text, "Je te propose d'alleger demain — tu confirmes ?")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.mutation_type, "plan_patch")
        self.assertIn("lighten_day", pending.decision_json)

    def test_llm_generate_does_not_create_pending_when_final_reply_does_not_confirm(self) -> None:
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="validate_plan_patch",
                        input={
                            "patch": {
                                "coach_message": "Je teste un ajustement.",
                                "operations": [
                                    {
                                        "operation_type": "lighten_day",
                                        "target_session_id": 10,
                                        "rationale": "Charge haute.",
                                    }
                                ],
                            }
                        },
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Je garde juste un oeil sur demain.")],
            ),
        ]

        def fake_request_message(**_kwargs):
            return responses.pop(0)

        context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-05-04T07:30:00+02:00"),
            scheduled_sessions=[
                {
                    "id": 10,
                    "scheduled_date": "2026-05-05T07:00:00+02:00",
                    "sport_type": "running",
                    "session_title": "Footing facile",
                    "duration_min": 35,
                    "completion_status": "planned",
                }
            ],
        )

        original_request_message = tool_loop.gw.request_message
        original_request_text = heartbeat.request_text
        try:
            tool_loop.gw.request_message = fake_request_message
            heartbeat.request_text = lambda **_kwargs: "ALLOW"
            text = heartbeat._llm_generate(
                "system",
                "prompt",
                pipeline="heartbeat_signal",
                tool_context=context,
            )
            pending = heartbeat._take_pending_confirmation()
        finally:
            tool_loop.gw.request_message = original_request_message
            heartbeat.request_text = original_request_text

        self.assertEqual(text, "Je garde juste un oeil sur demain.")
        self.assertIsNone(pending)


if __name__ == "__main__":
    unittest.main()
