from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from fitmas.domain.planning import repository as planning_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-command-bus-", suffix=".db"))

from fitmas.core import orm as s
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.decision import Command
from fitmas.decision.command_application import RuntimeCommandBus
from fitmas.core.time_context import DAY_KEYS, day_label_fr


class RuntimeCommandBusTest(unittest.TestCase):
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

    def test_applies_memory_command_and_returns_event_backed_result(self) -> None:
        bus = RuntimeCommandBus(db=self.db, user=self.user, source="coach_decision")
        command = Command(
            id="memory:0:record_availability",
            domain="memory",
            name="record_availability",
            payload={
                "type": "record_availability",
                "window_text": "piscine fermee",
                "availability": "unavailable",
                "sport_type": "swimming",
                "starts_on": "2026-05-14",
                "ends_on": "2026-05-28",
                "confidence": 0.9,
                "evidence": "piscine fermee",
            },
        )

        results = bus.apply((command,))

        events = self.db.query(s.MemoryMutationEventRecord).all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(results[0].event_id, f"memory_mutation_event:{events[0].id}")
        self.assertEqual(results[0].payload["saved_keys"], ("availability:unavailable_swimming_2026-05-14_2026-05-28",))

    def test_applies_execution_command_and_returns_updated_session(self) -> None:
        session = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo")
        bus = RuntimeCommandBus(db=self.db, user=self.user, source="coach_decision")
        command = Command(
            id="execution:0:record_execution_update",
            domain="execution",
            name="record_execution_update",
            payload={
                "type": "record_execution_update",
                "target_ref": session.scheduled_date.date().isoformat(),
                "status": "not_completed",
                "completed": False,
                "sport_type": "strength",
                "confidence": 0.95,
                "evidence": "pas fait",
            },
        )

        results = bus.apply((command,))

        updated = planning_repo.get_scheduled_session(self.db, self.user.id, session.id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(results[0].payload["updated_session_ids"], (session.id,))
        self.assertEqual(updated.completion_status, "skipped")

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
            duration_min=30,
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
