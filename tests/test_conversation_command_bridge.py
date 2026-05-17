from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-command-bridge-", suffix=".db"))

from fitmas import schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.decision import CoachUnderstanding, UserSignal
from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.legacy.conversation_command_bridge import apply_coach_decision_commands, apply_turn_plan_memory_commands
from fitmas.llm import AvailabilityConstraintAction, CoachDecision


class ConversationCommandBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_apply_coach_decision_commands_returns_legacy_metric_payload_and_writes(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="bridge should preserve legacy action metrics",
            fitmas_message="ok",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="piscine fermee",
                    availability="unavailable",
                    sport_type="swimming",
                    starts_on="2026-05-14",
                    ends_on="2026-05-28",
                    confidence=0.9,
                    evidence="piscine fermee",
                ),
            ),
        )

        metrics = apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            turn_memory_writes=writes,
            unresolved_execution_followup=None,
            turn_plan=None,
            canonical_understanding=None,
        )

        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(metrics["execution_applied"], 0)
        self.assertEqual(writes[0]["category"], "availability")
        self.assertEqual(writes[0]["source"], "coach_decision")
        self.assertEqual(writes[0]["action"], "applied")

    def test_apply_turn_plan_memory_commands_uses_command_bus(self) -> None:
        writes: list[dict] = []
        turn_context: dict[str, object] = {}
        turn_plan = SimpleNamespace(
            availability_constraint={
                "availability": "unavailable",
                "sport_type": "swimming",
                "scope": "sport",
                "starts_on": "2026-05-14",
                "ends_on": "2026-05-28",
            },
            confidence=0.8,
        )

        apply_turn_plan_memory_commands(
            db=self.db,
            user=self.user,
            turn_plan=turn_plan,
            turn_memory_writes=writes,
            turn_context=turn_context,
        )

        self.assertEqual(writes[0]["category"], "availability")
        self.assertEqual(writes[0]["source"], "turn_plan")
        self.assertEqual(turn_context["turn_plan_memory_action_result"]["memory_applied"], 1)

    def test_commands_from_understanding_flag_uses_canonical_memory_commands(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy has no actions",
            fitmas_message="ok",
            memory_actions=(),
        )

        old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
        os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "1"
        try:
            metrics = apply_coach_decision_commands(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                turn_memory_writes=writes,
                unresolved_execution_followup=None,
                turn_plan=None,
                canonical_understanding=_understanding_with_availability_signal(),
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.assertEqual(metrics["command_source"], "coach_understanding")
        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(metrics["execution_applied"], 0)
        self.assertEqual(writes[0]["source"], "coach_understanding")
        self.assertEqual(writes[0]["category"], "availability")

    def test_commands_from_understanding_flag_uses_canonical_execution_commands(self) -> None:
        session = self._scheduled_session()
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy has no actions",
            fitmas_message="ok",
            execution_actions=(),
        )

        old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
        os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "1"
        try:
            metrics = apply_coach_decision_commands(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                turn_memory_writes=writes,
                unresolved_execution_followup=None,
                turn_plan=None,
                canonical_understanding=_understanding_with_execution_signal(session.id),
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.db.expire_all()
        refreshed = self.db.get(s.ScheduledSession, session.id)
        self.assertEqual(metrics["command_source"], "coach_understanding")
        self.assertEqual(metrics["memory_applied"], 0)
        self.assertEqual(metrics["execution_applied"], 1)
        self.assertEqual(metrics["execution_updated_session_ids"], (session.id,))
        self.assertEqual(writes[0]["source"], "coach_understanding")
        self.assertEqual(writes[0]["category"], "execution")
        self.assertEqual(refreshed.completion_status, "done")

    def test_commands_from_understanding_flag_falls_back_when_empty(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy carries memory action",
            fitmas_message="ok",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="piscine fermee",
                    availability="unavailable",
                    sport_type="swimming",
                    starts_on="2026-05-15",
                    ends_on="2026-05-29",
                    confidence=0.9,
                    evidence="legacy action",
                ),
            ),
        )
        empty_understanding = CoachUnderstanding(
            intent="general_answer",
            confidence=0.7,
            user_summary="no command",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=None,
            clarification_need=None,
        )

        old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
        os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "1"
        try:
            metrics = apply_coach_decision_commands(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                turn_memory_writes=writes,
                unresolved_execution_followup=None,
                turn_plan=None,
                canonical_understanding=empty_understanding,
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.assertEqual(metrics["command_source"], "coach_decision")
        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(writes[0]["source"], "coach_decision")

    def test_commands_from_understanding_default_on_when_artifact_exists(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy has no actions",
            fitmas_message="ok",
            memory_actions=(),
        )

        old_flag = os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
        try:
            metrics = apply_coach_decision_commands(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                turn_memory_writes=writes,
                unresolved_execution_followup=None,
                turn_plan=None,
                canonical_understanding=_understanding_with_availability_signal(),
            )
        finally:
            if old_flag is not None:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.assertEqual(metrics["command_source"], "coach_understanding")
        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(writes[0]["source"], "coach_understanding")

    def test_commands_from_understanding_can_be_disabled(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy carries action",
            fitmas_message="ok",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="piscine fermee",
                    availability="unavailable",
                    sport_type="swimming",
                    starts_on="2026-05-14",
                    ends_on="2026-05-28",
                    confidence=0.9,
                    evidence="piscine fermee",
                ),
            ),
        )

        old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
        os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "0"
        try:
            metrics = apply_coach_decision_commands(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                turn_memory_writes=writes,
                unresolved_execution_followup=None,
                turn_plan=None,
                canonical_understanding=_understanding_with_availability_signal(),
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.assertEqual(metrics["command_source"], "coach_decision")
        self.assertEqual(writes[0]["source"], "coach_decision")

    def _scheduled_session(self) -> s.ScheduledSession:
        session = s.ScheduledSession(
            user_id=self.user.id,
            day="friday",
            label="Vendredi",
            scheduled_date=datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0, tzinfo=None),
            sport_type="running",
            session_type="easy",
            session_title="Footing facile",
            session_goal="Relancer propre",
            duration_min=40,
            intensity="easy",
            load_score=2,
            priority="Normal",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session


if __name__ == "__main__":
    unittest.main()


def _understanding_with_availability_signal() -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="availability_signal",
        confidence=0.91,
        user_summary="Piscine indisponible pendant deux semaines.",
        extracted_signals=(
            UserSignal(
                type="availability",
                label="piscine fermee",
                status="new",
                severity="medium",
                confidence=0.9,
                evidence="piscine fermee deux semaines",
                payload={
                    "availability": "unavailable",
                    "sport_type": "swimming",
                    "scope": "sport",
                    "starts_on": "2026-05-15",
                    "ends_on": "2026-05-29",
                    "window_text": "piscine fermee deux semaines",
                },
            ),
        ),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )


def _understanding_with_execution_signal(session_id: int) -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="execution_report",
        confidence=0.92,
        user_summary="La seance cible est faite.",
        extracted_signals=(
            UserSignal(
                type="execution",
                label="seance faite",
                status="new",
                severity="low",
                confidence=0.9,
                evidence="j'ai fait la seance",
                payload={
                    "target_ref": "session cible",
                    "target_session_id": session_id,
                    "status": "completed",
                    "completed": True,
                    "sport_type": "running",
                    "duration_min": 40,
                },
            ),
        ),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
