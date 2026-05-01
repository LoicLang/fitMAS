from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-memory-service-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.execution_mutation_service import apply_execution_actions_for_user
from fitmas.llm import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
    PreferenceSignalAction,
)
from fitmas.memory_mutation_service import apply_memory_actions_for_user
from fitmas.time_context import DAY_KEYS, day_label_fr


class MutationActionServicesTest(unittest.TestCase):
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

    def test_memory_service_routes_actions_to_bounded_memory_and_audit(self) -> None:
        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="demain soir",
                    availability="unavailable",
                    starts_on="2026-05-01",
                    ends_on="2026-05-01",
                    confidence=0.91,
                    evidence="indispo demain soir",
                ),
                PreferenceSignalAction(
                    type="record_preference",
                    preference="prefere les reponses directes sans menu",
                    polarity="prefer",
                    scope="conversation",
                    confidence=0.82,
                    evidence="je te demande rien",
                ),
            ],
        )

        facts = self.db.query(s.UserFact).order_by(s.UserFact.id).all()
        working = self.db.query(s.WorkingMemoryEntry).order_by(s.WorkingMemoryEntry.id).all()
        events = self.db.query(s.MemoryMutationEventRecord).order_by(s.MemoryMutationEventRecord.id).all()

        self.assertEqual(result.applied_count, 2)
        self.assertEqual([fact.category for fact in facts], ["preference"])
        self.assertEqual(facts[0].key, "preference_prefer_reponses_directes_sans_menu")
        self.assertEqual([entry.category for entry in working], ["availability"])
        self.assertEqual(working[0].key, "availability_2026-05-01_2026-05-01")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.status == "applied" for event in events))

    def test_execution_service_marks_unique_target_skipped_and_audits(self) -> None:
        session = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo 34min")

        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref="seance renfo d'hier",
                    status="not_completed",
                    completed=False,
                    sport_type="strength",
                    confidence=0.94,
                    evidence="pas eu le temps hier",
                )
            ],
        )

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        events = self.db.query(s.MemoryMutationEventRecord).order_by(s.MemoryMutationEventRecord.id).all()

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(updated.completion_status, "skipped")
        self.assertEqual(events[0].action_type, "record_execution_update")
        self.assertEqual(events[0].status, "applied")

    def test_execution_service_prefers_structured_session_id(self) -> None:
        session = self._scheduled_session(days_offset=0, sport_type="running", title="Footing")

        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref="seance cible depuis tool",
                    target_session_id=session.id,
                    status="completed",
                    completed=True,
                    confidence=0.97,
                    evidence="done",
                )
            ],
        )

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(updated.completion_status, "done")

    def test_execution_service_refuses_ambiguous_target_without_write(self) -> None:
        first = self._scheduled_session(days_offset=-1, sport_type="running", title="Footing")
        second = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo")

        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref="seance d'hier",
                    status="not_completed",
                    completed=False,
                    confidence=0.9,
                    evidence="pas eu le temps hier",
                )
            ],
        )

        self.db.expire_all()
        events = self.db.query(s.MemoryMutationEventRecord).order_by(s.MemoryMutationEventRecord.id).all()

        self.assertEqual(result.applied_count, 0)
        self.assertEqual(result.blocked_count, 1)
        self.assertEqual(repo.get_scheduled_session(self.db, self.user.id, first.id).completion_status, "planned")
        self.assertEqual(repo.get_scheduled_session(self.db, self.user.id, second.id).completion_status, "planned")
        self.assertEqual(events[0].status, "blocked")
        self.assertEqual(events[0].reason, "ambiguous_target")

    def _scheduled_session(self, *, days_offset: int, sport_type: str, title: str) -> s.ScheduledSession:
        target = datetime.now() + timedelta(days=days_offset)
        day_key = DAY_KEYS[target.weekday()]
        session = s.ScheduledSession(
            user_id=self.user.id,
            day=day_key,
            label=day_label_fr(day_key, capitalize=True),
            scheduled_date=target.replace(hour=8, minute=0, second=0, microsecond=0),
            sport_type=sport_type,
            session_type="easy",
            session_title=title,
            session_goal=title,
            duration_min=34,
            intensity="easy",
            load_score=1,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session


if __name__ == "__main__":
    unittest.main()
