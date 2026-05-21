from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from fitmas.tools.contract import ToolCall, ToolContext
from fitmas.tools.registry import build_tool_registry, list_tools_for_pipeline
from fitmas.tools.runtime import execute_tool_call, execute_tool_calls
from fitmas.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


class ToolRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 12,
                    "scheduled_date": "2026-03-22T07:00:00+01:00",
                    "sport_type": "swimming",
                    "session_title": "Natation",
                    "duration_min": 60,
                    "completion_status": "planned",
                },
                {
                    "id": 13,
                    "scheduled_date": "2026-03-24T07:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing",
                    "duration_min": 45,
                    "completion_status": "planned",
                },
            ],
            activities=[
                {
                    "id": 33,
                    "started_at": "2026-03-21T18:00:00+01:00",
                    "sport_type": "running",
                    "title": "Footing long",
                    "duration_min": 70,
                    "distance_m": 14000,
                    "avg_speed": 3.3,
                },
                {
                    "id": 34,
                    "started_at": "2026-03-20T18:00:00+01:00",
                    "sport_type": "cycling",
                    "title": "Velo",
                    "duration_min": 90,
                    "distance_m": 36000,
                    "avg_speed": 8.2,
                },
            ],
            active_facts=[
                {
                    "category": "goal",
                    "key": "running_focus",
                    "value": "Retrouver mon niveau running",
                    "source": "conversation",
                    "confidence": 0.9,
                    "confirmed": True,
                    "active": True,
                }
            ],
        )

    def test_registry_exposes_conversation_tools(self) -> None:
        tools = list_tools_for_pipeline("conversation")
        names = {tool["name"] for tool in tools}
        by_name = {tool["name"]: tool for tool in tools}

        self.assertIn("get_today_context", names)
        self.assertIn("suggest_replan_candidates", names)
        self.assertIn("resolve_planning_window", names)
        self.assertIn("get_recent_activities", names)
        self.assertIn("get_relevant_facts", names)
        self.assertIn("get_recent_reality_window", names)
        self.assertIn("get_load_context", names)
        self.assertIn("get_coach_lens", names)
        self.assertIn("validate_plan_patch", names)
        self.assertNotIn("propose_replan", names)
        self.assertNotIn("draft_move_session", names)
        self.assertNotIn("draft_swap_sessions", names)
        self.assertNotIn("draft_replace_session", names)
        self.assertNotIn("draft_lighten_day", names)
        self.assertNotIn("draft_create_session", names)
        self.assertNotIn("validate_week_coherence", names)
        self.assertEqual(by_name["suggest_replan_candidates"]["kind"], "candidate")
        self.assertEqual(by_name["validate_plan_patch"]["kind"], "validation")

        planning_tools = list_tools_for_pipeline("planning")
        planning_by_name = {tool["name"]: tool for tool in planning_tools}
        self.assertIn("validate_week_coherence", planning_by_name)
        self.assertEqual(planning_by_name["validate_week_coherence"]["kind"], "validation")

    def test_registry_exposes_heartbeat_candidate_validation_tools_without_legacy_write(self) -> None:
        names = {tool["name"] for tool in list_tools_for_pipeline("heartbeat")}

        self.assertIn("get_plan_window", names)
        self.assertIn("get_recent_activities", names)
        self.assertIn("get_activity_highlights", names)
        self.assertIn("get_recent_reality_window", names)
        self.assertIn("get_load_context", names)
        self.assertIn("get_user_constraints", names)
        self.assertIn("get_relevant_facts", names)
        self.assertIn("suggest_replan_candidates", names)
        self.assertIn("validate_plan_patch", names)
        self.assertIn("validate_week_coherence", names)
        self.assertNotIn("resolve_planning_window", names)
        self.assertNotIn("propose_replan", names)
        self.assertNotIn("draft_move_session", names)
        self.assertNotIn("draft_swap_sessions", names)
        self.assertNotIn("draft_replace_session", names)
        self.assertNotIn("draft_lighten_day", names)
        self.assertNotIn("draft_create_session", names)

    def test_execute_tool_call_returns_today_context(self) -> None:
        result, trace = execute_tool_call(
            ToolCall(tool_name="get_today_context"),
            context=self.context,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["planned_sport"], "swimming")
        self.assertEqual(trace.tool_name, "get_today_context")
        self.assertTrue(trace.tool_success)
        self.assertTrue(trace.tool_called)

    def test_execute_tool_call_rejects_unknown_tool(self) -> None:
        result, trace = execute_tool_call(
            ToolCall(tool_name="unknown_tool"),
            context=self.context,
        )

        self.assertEqual(result.status, "error")
        self.assertIn("Unknown tool", result.error)
        self.assertFalse(trace.tool_called)
        self.assertFalse(trace.tool_success)

    def test_execute_tool_call_rejects_wrong_pipeline(self) -> None:
        planning_only_context = ToolContext(
            pipeline="heartbeat",
            user_id=1,
            timezone_name="Europe/Paris",
        )
        result, trace = execute_tool_call(
            ToolCall(tool_name="get_today_context"),
            context=planning_only_context,
        )

        self.assertEqual(result.status, "error")
        self.assertIn("not allowed", result.error)
        self.assertFalse(trace.tool_called)

    def test_execute_tool_calls_runs_batch_and_blocks_surplus(self) -> None:
        results = execute_tool_calls(
            [
                ToolCall(tool_name="get_today_context"),
                ToolCall(tool_name="get_plan_window"),
                ToolCall(tool_name="get_recent_activities"),
                ToolCall(tool_name="get_load_context"),
            ],
            context=self.context,
            max_tools=3,
        )

        self.assertEqual([item.result.tool_name for item in results], [
            "get_today_context",
            "get_plan_window",
            "get_recent_activities",
            "get_load_context",
        ])
        self.assertEqual([item.result.status for item in results], ["ok", "ok", "ok", "error"])
        self.assertEqual(results[-1].result.error, "tool_budget_exceeded")
        self.assertFalse(results[-1].trace.tool_called)

    def test_execute_tool_calls_deduplicates_identical_calls_without_spending_budget(self) -> None:
        results = execute_tool_calls(
            [
                ToolCall(tool_name="get_today_context", arguments={}),
                ToolCall(tool_name="get_today_context", arguments={}),
                ToolCall(tool_name="get_plan_window", arguments={}),
            ],
            context=self.context,
            max_tools=1,
        )

        self.assertEqual([item.result.status for item in results], ["ok", "ok", "error"])
        self.assertEqual(results[0].result.payload, results[1].result.payload)
        self.assertTrue(results[0].trace.tool_called)
        self.assertFalse(results[1].trace.tool_called)
        self.assertTrue(results[1].trace.tool_success)
        self.assertIn("deja lu", results[1].result.summary.lower())
        self.assertEqual(results[2].result.error, "tool_budget_exceeded")

    def test_activity_highlights_returns_best_efforts(self) -> None:
        registry = build_tool_registry()
        result = registry["get_activity_highlights"].handler(self.context, {"days": 14})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["longest_duration"]["title"], "Velo")
        self.assertEqual(result.payload["longest_distance"]["title"], "Velo")
        self.assertEqual(result.payload["fastest"]["title"], "Velo")

    def test_coach_lens_returns_compact_context_without_full_plan_window(self) -> None:
        registry = build_tool_registry()
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            scheduled_sessions=[
                *self.context.scheduled_sessions,
                {
                    "id": 14,
                    "scheduled_date": "2026-03-26T07:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Footing Z2",
                    "duration_min": 40,
                    "completion_status": "planned",
                },
                {
                    "id": 15,
                    "scheduled_date": "2026-03-28T07:00:00+01:00",
                    "sport_type": "strength",
                    "session_title": "Renfo",
                    "duration_min": 45,
                    "completion_status": "planned",
                },
            ],
            activities=self.context.activities,
            active_facts=[
                *self.context.active_facts,
                {
                    "category": "health",
                    "key": "shin_tension",
                    "value": "Tension tibias legere a surveiller",
                    "active": True,
                    "urgency": "medium",
                    "confirmed": True,
                },
            ],
        )

        result = registry["get_coach_lens"].handler(context, {"plan_limit": 2, "fact_limit": 4})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["as_of_date"], "2026-03-22")
        self.assertEqual([item["id"] for item in result.payload["near_plan"]], [12, 13])
        self.assertLessEqual(len(result.payload["near_plan"]), 2)
        self.assertEqual(result.payload["recent_reality"]["activity_count"], 2)
        self.assertEqual(result.payload["recent_reality"]["duration_min"], 160)
        self.assertEqual(result.payload["active_signals"][0]["key"], "shin_tension")
        self.assertEqual(result.payload["durable_facts"][0]["key"], "running_focus")
        self.assertIn("read_only", result.payload["usage_guidance"])
        self.assertNotIn("sessions", result.payload)

    def test_resolve_planning_window_matches_single_candidate(self) -> None:
        registry = build_tool_registry()
        result = registry["resolve_planning_window"].handler(
            self.context,
            {
                "reference_label": "mardi matin",
                "resolved_date": "2026-03-24",
                "window": "morning",
                "scope": "single_window",
            },
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["matched_session_id"], 13)
        self.assertTrue(result.payload["exact_match"])

    def test_recent_reality_window_returns_plan_and_actual(self) -> None:
        registry = build_tool_registry()
        result = registry["get_recent_reality_window"].handler(self.context, {"days": 7, "limit": 4})

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.payload["planned_sessions"]), 1)
        self.assertEqual(len(result.payload["activities"]), 2)
        self.assertEqual(result.payload["planned_sessions"][0]["session_title"], "Natation")

    def test_load_context_summarizes_recent_and_upcoming_load(self) -> None:
        registry = build_tool_registry()
        result = registry["get_load_context"].handler(self.context, {"days": 7})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["recent_actual_duration_min"], 160)
        self.assertEqual(result.payload["upcoming_planned_duration_min"], 105)
        self.assertEqual(result.payload["upcoming_planned_session_count"], 2)

    def test_load_context_includes_ctl_atl_tsb_snapshot(self) -> None:
        """Chantier 2: get_load_context expose ATL/CTL/TSB pour donner au
        coach LLM une lecture chiffree de la fatigue/forme."""
        registry = build_tool_registry()
        result = registry["get_load_context"].handler(self.context, {"days": 7})

        self.assertEqual(result.status, "ok")
        self.assertIn("ctl", result.payload)
        self.assertIn("atl", result.payload)
        self.assertIn("tsb", result.payload)
        self.assertIn("fitness_label", result.payload)
        self.assertEqual(result.payload["as_of_date"], "2026-03-22")
        self.assertGreater(float(result.payload["ctl"]), 0.0)
        self.assertGreater(float(result.payload["atl"]), 0.0)
        self.assertIn(result.payload["fitness_label"], {"frais", "neutre", "fatigue"})

    def test_user_constraints_returns_active_availability_facts(self) -> None:
        """Chantier 2: get_user_constraints filtre les facts par categorie
        (availability/schedule/constraint/health/fatigue) et exclut les
        facts inactifs ou expires."""
        from datetime import timedelta

        future = datetime.fromisoformat("2026-04-30T00:00:00+00:00")
        past = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            scheduled_sessions=(),
            activities=(),
            active_facts=[
                {
                    "category": "availability",
                    "key": "pool_closed",
                    "value": "Piscine fermee 2 semaines",
                    "active": True,
                    "expires_at": future,
                    "urgency": "high",
                    "confirmed": True,
                },
                {
                    "category": "health",
                    "key": "knee_pain",
                    "value": "Douleur genou gauche",
                    "active": True,
                    "expires_at": None,
                    "urgency": "medium",
                    "confirmed": True,
                },
                {
                    "category": "preference",
                    "key": "morning_runner",
                    "value": "Court mieux le matin",
                    "active": True,
                    "expires_at": None,
                },
                {
                    "category": "availability",
                    "key": "expired_constraint",
                    "value": "Voyage termine",
                    "active": True,
                    "expires_at": past,
                },
                {
                    "category": "availability",
                    "key": "inactive",
                    "value": "Annule",
                    "active": False,
                    "expires_at": future,
                },
            ],
        )

        registry = build_tool_registry()
        result = registry["get_user_constraints"].handler(context, {})

        self.assertEqual(result.status, "ok")
        keys = {item["key"] for item in result.payload["constraints"]}
        self.assertEqual(keys, {"pool_closed", "knee_pain"})
        for item in result.payload["constraints"]:
            if item["key"] == "pool_closed":
                self.assertEqual(item["category"], "availability")
                self.assertIsNotNone(item["expires_at"])

    def test_user_constraints_respects_categories_filter(self) -> None:
        registry = build_tool_registry()
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            active_facts=[
                {"category": "availability", "key": "a", "value": "x", "active": True, "expires_at": None},
                {"category": "health", "key": "b", "value": "y", "active": True, "expires_at": None},
            ],
        )
        result = registry["get_user_constraints"].handler(context, {"categories": ["health"]})

        self.assertEqual(result.status, "ok")
        keys = {item["key"] for item in result.payload["constraints"]}
        self.assertEqual(keys, {"b"})

    def test_suggest_replan_candidates_returns_valid_replacement_for_active_swim_constraint(self) -> None:
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.fromisoformat("2026-03-22T19:56:00+01:00"),
            scheduled_sessions=[
                {
                    "id": 21,
                    "scheduled_date": "2026-03-23T18:00:00+01:00",
                    "sport_type": "running",
                    "session_title": "Tempo demain",
                    "session_type": "tempo",
                    "duration_min": 50,
                    "intensity": "moderate",
                    "priority": "Seance cle",
                    "completion_status": "planned",
                },
                {
                    "id": 22,
                    "scheduled_date": "2026-03-24T07:00:00+01:00",
                    "sport_type": "swimming",
                    "session_title": "Natation endurance",
                    "session_type": "endurance",
                    "duration_min": 45,
                    "intensity": "easy",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
                {
                    "id": 23,
                    "scheduled_date": "2026-03-25T07:00:00+01:00",
                    "sport_type": "strength",
                    "session_title": "Renfo support",
                    "session_type": "strength",
                    "duration_min": 30,
                    "intensity": "moderate",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
            ],
            active_facts=[
                {
                    "category": "availability",
                    "key": "unavailable_swimming_2026-03-23_2026-04-05",
                    "value": "Piscine fermee pendant 2 semaines",
                    "active": True,
                    "expires_at": datetime.fromisoformat("2026-04-06T00:00:00+00:00"),
                }
            ],
        )

        registry = build_tool_registry()
        result = registry["suggest_replan_candidates"].handler(context, {})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["constraint"]["sport_type"], "swimming")
        self.assertEqual(result.payload["recommended_mutation"]["mutation_type"], "replace_session")
        self.assertEqual(result.payload["recommended_mutation"]["target_session_id"], 22)
        self.assertTrue(result.payload["validation"]["is_valid"])
        self.assertTrue(result.payload["scope"]["covers_all_impacted_sessions"])
        self.assertEqual(result.payload["scope"]["covered_session_ids"], [22])

    def test_validate_plan_patch_tool_returns_valid_for_clean_move(self) -> None:
        registry = build_tool_registry()
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            scheduled_sessions=[
                {
                    "id": 41,
                    "scheduled_date": "2099-03-23T07:00:00+01:00",
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "duration_min": 45,
                    "intensity": "easy",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
                {
                    "id": 42,
                    "scheduled_date": "2099-03-24T07:00:00+01:00",
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Repos flexible",
                    "duration_min": 0,
                    "intensity": "easy",
                    "priority": "Recovery",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                },
            ],
        )

        result = registry["validate_plan_patch"].handler(
            context,
            {
                "patch": {
                    "coach_message": "Je peux bouger le footing a mardi.",
                    "operations": [
                        {
                            "operation_type": "move_session",
                            "target_session_id": 41,
                            "target_date": "2099-03-24",
                            "rationale": "Jour cible libre.",
                        }
                    ],
                }
            },
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["status"], "valid")
        self.assertEqual(result.payload["operation_results"][0]["status"], "valid")
        self.assertEqual(result.summary, "Patch valide.")

    def test_validate_week_coherence_tool_returns_review_payload_without_write(self) -> None:
        registry = build_tool_registry()
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            scheduled_sessions=[
                {
                    "id": 91,
                    "scheduled_date": "2099-03-23T07:00:00+01:00",
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "duration_min": 45,
                    "intensity": "easy",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
                {
                    "id": 92,
                    "scheduled_date": "2099-03-24T07:00:00+01:00",
                    "sport_type": "rest",
                    "session_type": "rest",
                    "session_title": "Repos flexible",
                    "duration_min": 0,
                    "intensity": "easy",
                    "priority": "Recovery",
                    "flexibility": "flexible",
                    "completion_status": "planned",
                },
            ],
            active_facts=(
                {"category": "goal", "key": "main", "value": "10 km", "active": True},
            ),
        )
        patch_payload = {
            "coach_message": "Je peux bouger le footing a mardi.",
            "operations": [
                {
                    "operation_type": "move_session",
                    "target_session_id": 91,
                    "target_date": "2099-03-24",
                    "rationale": "Jour cible libre.",
                }
            ],
        }
        review = WeekCoherenceReview(
            status="valid",
            sport_quality="good",
            confidence=0.9,
            summary="Semaine coherente apres deplacement.",
            findings=(
                WeekCoherenceFinding(
                    code="mission_preserved",
                    severity="info",
                    detail="Le stimulus reste coherent.",
                    target_session_ids=(91,),
                ),
            ),
            suggested_adjustments=(),
            recommended_policy="commit_original",
        )

        with patch("fitmas.tools.registry.review_week_coherence_with_llm", return_value=review, create=True):
            result = registry["validate_week_coherence"].handler(context, {"patch": patch_payload})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["validation"]["status"], "valid")
        self.assertEqual(result.payload["review"]["status"], "valid")
        self.assertEqual(result.payload["review"]["recommended_policy"], "commit_original")
        self.assertEqual(result.payload["deterministic_checks"]["weekly_duration_delta_min"], 0)
        self.assertEqual(result.payload["facts"]["total_sessions_after"], 2)
        self.assertIn("total", result.payload["score"])
        self.assertEqual(result.payload["coherence_findings"][0]["code"], "NO_STRUCTURAL_WEEK_RISK_DETECTED")
        self.assertFalse(result.payload["commit_performed"])
        self.assertEqual(result.payload["writer"], "none")

    def test_validate_plan_patch_tool_blocks_occupied_target_with_suggested_fix(self) -> None:
        registry = build_tool_registry()
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            scheduled_sessions=[
                {
                    "id": 51,
                    "scheduled_date": "2099-03-23T07:00:00+01:00",
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "duration_min": 45,
                    "intensity": "easy",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
                {
                    "id": 52,
                    "scheduled_date": "2099-03-24T07:00:00+01:00",
                    "sport_type": "cycling",
                    "session_type": "endurance",
                    "session_title": "Velo endurance",
                    "duration_min": 75,
                    "intensity": "moderate",
                    "priority": "Normal",
                    "completion_status": "planned",
                },
            ],
        )

        result = registry["validate_plan_patch"].handler(
            context,
            {
                "patch": {
                    "coach_message": "Je bouge le footing a mardi.",
                    "operations": [
                        {
                            "operation_type": "move_session",
                            "target_session_id": 51,
                            "target_date": "2099-03-24",
                            "rationale": "Tester le blocage.",
                        }
                    ],
                }
            },
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload["status"], "blocked")
        operation = result.payload["operation_results"][0]
        self.assertEqual(operation["block_reason"], "occupied_training_target")
        self.assertIn("swap_sessions", operation["suggested_fix"])

if __name__ == "__main__":
    unittest.main()
