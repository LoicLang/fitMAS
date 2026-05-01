"""Real integration tests hitting the configured LLM API.

Run with: PYTHONPATH=backend/src .venv/bin/python -m pytest tests/test_integration_real.py -v -s
Requires DEEPSEEK_API_KEY (preferred) or ANTHROPIC_API_KEY in .env
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fitmas.llm_gateway import client, request_text, request_json, request_message, message_text, message_json
from fitmas.tools.routing import IntentCategory
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.prompt_layers import assemble_layered_prompt, build_identity_layer
from fitmas.llm_prompt_builder import (
    build_conversation_prompt_bundle,
    build_layered_conversation_prompt,
    _CONVERSATION_SYSTEM_TEXT,
)
from fitmas.mutation_hooks import (
    PreMutationResult,
    run_pre_mutation_hooks,
    run_post_mutation_hooks,
)
from fitmas.heartbeat_roles import (
    BRIEFING_ROLE,
    REMINDER_ROLE,
    REVIEW_ROLE,
    SIGNAL_ROLE,
    build_signal_prompt,
)
from fitmas.tool_contract import ToolCall, ToolContext, ToolResult
from fitmas.tool_runtime import execute_tool_call
from fitmas.time_context import build_time_context


def _skip_if_no_key():
    if os.getenv("FITMAS_RUN_REAL_LLM_TESTS") != "1":
        raise unittest.SkipTest("Set FITMAS_RUN_REAL_LLM_TESTS=1 to run real API tests")
    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
        raise unittest.SkipTest("No DEEPSEEK_API_KEY or ANTHROPIC_API_KEY — skipping real API tests")


# ---------------------------------------------------------------------------
# 1. Raw LLM connectivity
# ---------------------------------------------------------------------------

class TestLLMConnectivity(unittest.TestCase):
    def setUp(self):
        _skip_if_no_key()

    def test_client_is_available(self):
        c = client()
        self.assertIsNotNone(c, "LLM client should be available with API key")

    def test_simple_text_request(self):
        result = request_text(
            system="Tu es un coach sportif. Reponds en 1 phrase max.",
            prompt="Dis bonjour.",
            max_tokens=64,
        )
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)
        print(f"  LLM text response: {result}")

    def test_json_request(self):
        result = request_json(
            system="Reponds UNIQUEMENT avec un JSON valide: {\"sport\": \"...\", \"ok\": true}",
            prompt="Quel sport preferes-tu ?",
            max_tokens=128,
        )
        self.assertIsNotNone(result)
        self.assertIn("sport", result)
        print(f"  LLM JSON response: {result}")


# ---------------------------------------------------------------------------
# 2. Real conversation decide() call
# ---------------------------------------------------------------------------

class TestConversationDecide(unittest.TestCase):
    def setUp(self):
        _skip_if_no_key()

    def test_no_change_decision_for_casual_message(self):
        """A casual message should produce a no_change decision."""
        response = request_message(
            system=_CONVERSATION_SYSTEM_TEXT,
            messages=[{"role": "user", "content": (
                "Contexte temporel: Jeudi 3 avril 2026, 14h30.\n"
                "Calendrier date reel:\n"
                "- 2026-04-03 (Jeudi): Fractionne court (running) — planned\n"
                "- 2026-04-04 (Vendredi): Repos\n"
                "- 2026-04-05 (Samedi): Sortie longue (running) — planned\n\n"
                "Nouveau message de l'utilisateur:\n"
                "Salut, ca va bien ?"
            )}],
            max_tokens=512,
        )
        self.assertIsNotNone(response)
        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Response not valid JSON: {message_text(response)[:200]}")
        self.assertEqual(parsed.get("mutation_type"), "no_change")
        self.assertIn("fitmas_message", parsed)
        print(f"  Decision: {parsed['mutation_type']}")
        print(f"  Message: {parsed['fitmas_message'][:100]}")

    def test_move_decision_for_reschedule_request(self):
        """Asking to move a session should produce a move_session decision."""
        response = request_message(
            system=_CONVERSATION_SYSTEM_TEXT,
            messages=[{"role": "user", "content": (
                "Contexte temporel: Jeudi 3 avril 2026, 14h30.\n"
                "Calendrier date reel:\n"
                "- id=42 | date=2026-04-03 | day=thursday | slot=training | movable_target=false | swappable=true | [running/interval] Fractionne court | goal=Vitesse | status=planned\n"
                "- id=43 | date=2026-04-04 | day=friday | slot=free_flexible | movable_target=true | swappable=true | [rest/rest] Repos flexible | goal=Recuperer | status=planned\n"
                "- id=44 | date=2026-04-05 | day=saturday | slot=training | movable_target=false | swappable=true | [running/long] Sortie longue | goal=Endurance | status=planned\n\n"
                "Contexte coach:\n"
                "- session du jour id: 42\n\n"
                "Nouveau message de l'utilisateur:\n"
                "Je suis claque, je bascule la seance d'aujourd'hui a demain"
            )}],
            max_tokens=512,
        )
        self.assertIsNotNone(response)
        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Response not valid JSON: {message_text(response)[:200]}")
        self.assertIn(parsed.get("mutation_type"), ("move_session", "swap_sessions", "lighten_day"))
        print(f"  Decision: {parsed['mutation_type']}")
        print(f"  Target: session={parsed.get('target_session_id')}, date={parsed.get('target_date')}")
        print(f"  Message: {parsed.get('fitmas_message', '')[:100]}")

    def test_replace_decision_for_injury(self):
        """Reporting an injury should produce replace_session or lighten_day."""
        response = request_message(
            system=_CONVERSATION_SYSTEM_TEXT,
            messages=[{"role": "user", "content": (
                "Contexte temporel: Jeudi 3 avril 2026, 14h30.\n"
                "Calendrier date reel:\n"
                "- 2026-04-03 (Jeudi) [id=42]: Fractionne court (running) — planned\n"
                "- 2026-04-04 (Vendredi): Repos\n"
                "- 2026-04-05 (Samedi) [id=44]: Sortie longue (running) — planned\n\n"
                "Contexte coach:\n"
                "- session du jour id: 42\n\n"
                "Nouveau message de l'utilisateur:\n"
                "J'ai mal au genou droit depuis ce matin, je peux pas courir"
            )}],
            max_tokens=512,
        )
        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Response not valid JSON: {message_text(response)[:200]}")
        self.assertIn(
            parsed.get("mutation_type"),
            ("replace_session", "lighten_day", "no_change"),
        )
        print(f"  Decision: {parsed['mutation_type']}")
        print(f"  Message: {parsed.get('fitmas_message', '')[:100]}")


# ---------------------------------------------------------------------------
# 4. Prompt layers real LLM test
# ---------------------------------------------------------------------------

class TestPromptLayersWithLLM(unittest.TestCase):
    def setUp(self):
        _skip_if_no_key()

    def test_layered_prompt_produces_valid_response(self):
        """A layered prompt should produce a valid JSON decision from the LLM."""
        layered = assemble_layered_prompt(
            coach_context={
                "coach_name": "Coach Test",
                "coach_style": "direct et calme",
                "coach_soul": "Exigeant mais bienveillant",
            },
            profile_summary="Running: intermediaire, VMA 16. Cyclisme: debutant.",
            time_block="Contexte temporel: Jeudi 3 avril 2026, 14h30.",
            timeline_summary=(
                "- 2026-04-03 (Jeudi) [id=42]: Fractionne court (running) — planned\n"
                "- 2026-04-04 (Vendredi): Repos\n"
                "- 2026-04-05 (Samedi) [id=44]: Sortie longue (running) — planned"
            ),
            selected_facts=["[constraint] Ne court pas le lundi", "[health] Genou droit fragile"],
        )

        rendered = layered.render()
        self.assertIn("Coach Test", rendered)
        self.assertIn("Running: intermediaire", rendered)
        self.assertIn("Fractionne court", rendered)
        print(f"  Layered prompt length: {len(rendered)} chars, ~{len(rendered)//4} tokens")

        cache_points = layered.cache_breakpoints()
        print(f"  Cache breakpoints: {cache_points}")
        self.assertTrue(len(cache_points) >= 1, "Should have at least identity layer cacheable")

        # Actually call the LLM with the layered prompt
        response = request_message(
            system=[
                {"type": "text", "text": _CONVERSATION_SYSTEM_TEXT, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                {"type": "text", "text": rendered},
            ],
            messages=[{"role": "user", "content": "Nouveau message de l'utilisateur:\nOk ca roule pour aujourd'hui"}],
            max_tokens=512,
        )
        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Not valid JSON: {message_text(response)[:200]}")
        self.assertIn("mutation_type", parsed)
        self.assertIn("fitmas_message", parsed)
        print(f"  Decision: {parsed['mutation_type']}")
        print(f"  Message: {parsed['fitmas_message'][:100]}")


# ---------------------------------------------------------------------------
# 5. Mutation hooks integration test
# ---------------------------------------------------------------------------

class TestMutationHooksIntegration(unittest.TestCase):
    def test_pre_hooks_block_hard_training_collision(self):
        """Pre-hooks should block moves that would overwrite a real training day."""
        from fitmas.llm import MutationDecision

        decision = MutationDecision(
            mutation_type="move_session",
            target_session_id=42,
            target_date="2026-04-05",
            fitmas_message="Pas de souci, je deplace.",
            rationale="Fatigue",
        )

        mock_sessions = [
            {"id": 42, "scheduled_date": "2026-04-03", "sport_type": "running", "intensity": "moderate", "priority": "normal", "completion_status": "planned"},
            {"id": 44, "scheduled_date": "2026-04-05", "sport_type": "running", "intensity": "hard", "priority": "cle", "completion_status": "planned"},
        ]

        result = run_pre_mutation_hooks(
            MagicMock(),  # db mock
            plan_id=1,
            decision=decision,
            scheduled_sessions=mock_sessions,
            timezone_name="Europe/Paris",
        )

        self.assertFalse(result.allowed, "Should block training collisions")
        self.assertEqual(result.block_reason, "occupied_training_target")
        warning_codes = [w.code for w in result.warnings]
        self.assertIn("hard_session_collision", warning_codes)
        self.assertIn("occupied_training_target", warning_codes)
        print(f"  Warnings: {warning_codes}")

    def test_post_hooks_calculate_lighten_impact(self):
        """Post-hooks should correctly calculate impact of lightening a key session."""
        from fitmas.llm import MutationDecision

        decision = MutationDecision(
            mutation_type="lighten_day",
            target_session_id=42,
            fitmas_message="On allege.",
            rationale="Fatigue accumulee",
        )

        mock_sessions = [
            {"id": 42, "scheduled_date": "2026-04-03", "sport_type": "running", "session_title": "Fractionne cle",
             "intensity": "hard", "priority": "cle", "load_score": 3, "duration_min": 55, "completion_status": "planned"},
        ]

        result = run_post_mutation_hooks(
            MagicMock(),
            plan_id=1,
            decision=decision,
            scheduled_sessions=mock_sessions,
            timezone_name="Europe/Paris",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.impact.key_sessions_affected, 1)
        self.assertEqual(result.impact.delta_weekly_load, -3.0)
        self.assertEqual(result.impact.delta_weekly_duration_min, -55)
        print(f"  Impact: delta_load={result.impact.delta_weekly_load}, delta_duration={result.impact.delta_weekly_duration_min}")
        print(f"  Key affected: {result.impact.key_sessions_affected}")
        print(f"  Recalibration: {result.recalibration_triggered}")


# ---------------------------------------------------------------------------
# 6. Heartbeat roles real LLM test
# ---------------------------------------------------------------------------

class TestHeartbeatRolesWithLLM(unittest.TestCase):
    def setUp(self):
        _skip_if_no_key()

    def test_signal_role_generates_message(self):
        """Signal role should generate a contextual proactive message."""
        mock_user = MagicMock()
        mock_user.coach_name = "Coach FitMAS"
        mock_user.coach_style = "direct et calme"
        mock_user.coach_soul = "Exigeant mais bienveillant"

        system, prompt = build_signal_prompt(
            user=mock_user,
            time_context=build_time_context(
                "Europe/Paris",
                now=datetime(2026, 4, 3, 12, 30, tzinfo=timezone.utc),
            ),
            signals_block=(
                "Signaux actifs:\n"
                "- [warning] missed_key_session: La seance cle de mercredi (Fractionne) n'a pas ete faite.\n"
            ),
            facts_block="\n\nFaits actifs a prendre en compte:\n- [health] Douleur genou droit signale il y a 2 jours",
        )

        self.assertIn("Coach FitMAS", system)
        self.assertLessEqual(SIGNAL_ROLE.max_output_sentences, 3)

        result = request_text(system=system, prompt=prompt, max_tokens=256)
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 10)
        print(f"  Signal role output ({len(result)} chars): {result}")

    def test_role_capabilities_are_declared(self):
        """Each role should have explicit capabilities."""
        for role in (BRIEFING_ROLE, REMINDER_ROLE, REVIEW_ROLE, SIGNAL_ROLE):
            self.assertTrue(len(role.can_read) > 0, f"{role.name} should have read capabilities")
            self.assertTrue(len(role.can_write) > 0, f"{role.name} should have write capabilities")
            self.assertGreater(role.max_output_sentences, 0)
            print(f"  {role.name}: read={role.can_read}, write={role.can_write}, max_sentences={role.max_output_sentences}")


# ---------------------------------------------------------------------------
# 7. Tool observability hooks test
# ---------------------------------------------------------------------------

class TestToolObservabilityHooks(unittest.TestCase):
    def test_empty_result_gets_annotated(self):
        """Tool results with empty payloads should be annotated."""
        context = ToolContext(
            pipeline="conversation",
            user_id=1,
            timezone_name="Europe/Paris",
            now=datetime.now(timezone.utc),
            scheduled_sessions=[],
            activities=[],
        )

        call = ToolCall(tool_name="get_recent_activities", arguments={"days": 7})
        result, trace = execute_tool_call(call, context=context)

        self.assertEqual(result.status, "ok")
        self.assertIn("vide", result.summary.lower())
        print(f"  Summary: {result.summary}")
        print(f"  Trace: called={trace.tool_called}, success={trace.tool_success}")


# ---------------------------------------------------------------------------
# 8. Full pipeline simulation (no DB)
# ---------------------------------------------------------------------------

class TestFullPipelineSimulation(unittest.TestCase):
    def setUp(self):
        _skip_if_no_key()

    def test_casual_message_gets_minimal_context(self):
        """A casual message should use minimal prompt context and no tools."""
        user_text = "Ca va bien et toi ?"

        # Step 1: use explicit machine intent. Free user text is not routed
        # through a deterministic classifier anymore.
        intent = IntentCategory.CASUAL_CHAT

        # Step 2: get prompt policy
        policy = select_conversation_prompt_policy(intent=intent)
        self.assertFalse(policy.include_timeline)
        self.assertFalse(policy.include_signals)
        self.assertFalse(policy.include_facts)

        # Step 3: build prompt
        bundle = build_conversation_prompt_bundle(
            user_text=user_text,
            prompt_policy=policy,
            time_block="Contexte temporel: Jeudi 3 avril 2026, 14h30.",
            plan_summary="",
            timeline_summary=None,
            execution_summary=None,
            temporal_summary=None,
            activity_claim_summary=None,
            signal_summary=None,
            conversation_history=[],
            coach_context=None,
            selected_facts=[],
        )

        # Step 4: call LLM
        response = request_message(
            system=bundle.system,
            messages=[{"role": "user", "content": bundle.prompt}],
            max_tokens=512,
        )
        text = message_text(response)
        self.assertIsNotNone(text)
        print(f"  Casual response: {text[:200]}")

        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Response not valid JSON: {text[:200]}")
        self.assertEqual(parsed["mutation_type"], "no_change")
        print(f"  ✓ Correct: no_change for casual message")

    def test_plan_negotiation_gets_full_context(self):
        """A plan negotiation should use full context and produce a real mutation."""
        user_text = "Je deplace la seance de jeudi a vendredi"

        intent = IntentCategory.PLAN_NEGOTIATION

        policy = select_conversation_prompt_policy(intent=intent)
        self.assertTrue(policy.include_timeline)
        self.assertTrue(policy.include_signals)
        self.assertTrue(policy.include_facts)

        bundle = build_conversation_prompt_bundle(
            user_text=user_text,
            prompt_policy=policy,
            time_block="Contexte temporel: Jeudi 3 avril 2026, 14h30.",
            plan_summary="",
            timeline_summary=(
                "- 2026-04-03 (Jeudi) [id=42]: Fractionne court (running) — planned\n"
                "- 2026-04-04 (Vendredi): Repos\n"
                "- 2026-04-05 (Samedi) [id=44]: Sortie longue (running) — planned"
            ),
            execution_summary=None,
            temporal_summary=None,
            activity_claim_summary=None,
            signal_summary=None,
            conversation_history=[],
            coach_context={"coach_name": "FitMAS", "coach_style": "direct", "today_session_id": 42},
            selected_facts=["[constraint] Pas dispo le lundi"],
        )

        response = request_message(
            system=bundle.system,
            messages=[{"role": "user", "content": bundle.prompt}],
            max_tokens=512,
        )
        text = message_text(response)
        self.assertIsNotNone(text)
        print(f"  Negotiation response: {text[:300]}")

        parsed = message_json(response)
        self.assertIsNotNone(parsed, f"Response not valid JSON: {text[:200]}")
        self.assertEqual(parsed["mutation_type"], "move_session")
        self.assertIsNotNone(parsed.get("fitmas_message"))
        print(f"  ✓ Correct: move_session, target={parsed.get('target_session_id') or parsed.get('target_date')}")


if __name__ == "__main__":
    unittest.main()
