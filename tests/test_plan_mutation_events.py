from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-plan-mutations-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db


class PlanMutationEventsTest(unittest.TestCase):
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

    def test_add_plan_mutation_event_persists_json_payloads(self) -> None:
        row = repo.add_plan_mutation_event(
            self.db,
            user_id=self.user.id,
            source="conversation",
            trigger_type="message",
            command_type="move_session",
            target_session_ids=[10, 11],
            before_snapshot={"status": "planned"},
            after_snapshot={"status": "adapted"},
            reason={"rationale": "indispo"},
            impact={"delta_weekly_load": -2},
            user_visible_summary="Seance deplacee.",
            explained_to_user=True,
            conversation_turn_id=123,
        )

        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.command_type, "move_session")
        self.assertEqual(json.loads(row.target_session_ids_json), [10, 11])
        self.assertEqual(json.loads(row.before_snapshot_json), {"status": "planned"})
        self.assertEqual(json.loads(row.impact_json), {"delta_weekly_load": -2})
        self.assertTrue(row.explained_to_user)
        self.assertEqual(row.conversation_turn_id, 123)


if __name__ == "__main__":
    unittest.main()
