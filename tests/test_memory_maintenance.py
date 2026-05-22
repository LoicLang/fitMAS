from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-memory-maint-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.domain.memory.maintenance import run_memory_maintenance


class MemoryMaintenanceTest(unittest.TestCase):
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

    def test_run_memory_maintenance_purges_working_memory_and_promotes_patterns(self) -> None:
        self.db.add(
            s.WorkingMemoryEntry(
                user_id=self.user.id,
                category="fatigue",
                key="legs_today",
                value="Jambes lourdes aujourd'hui",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="high",
                ttl="immediate",
                scope="day",
                affects_json='["conversation"]',
                expires_at=(datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None),
            )
        )
        for created_at, text in [
            (datetime(2026, 3, 3, 17, 30), "Merde, je peux pas ce soir"),
            (datetime(2026, 3, 10, 17, 30), "Je peux pas ce soir"),
            (datetime(2026, 3, 17, 17, 30), "Imprevu, je peux pas ce soir"),
        ]:
            self.db.add(
                s.CoachMessage(
                    user_id=self.user.id,
                    role="user",
                    text=text,
                    created_at=created_at,
                )
            )
        self.db.commit()

        result = run_memory_maintenance(
            self.db,
            user_id=self.user.id,
            now=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
        )

        patterns = repo.get_active_patterns(self.db, self.user.id, limit=12)
        self.assertEqual(result.users_processed, 1)
        self.assertEqual(result.working_entries_archived, 1)
        self.assertGreaterEqual(result.patterns_upserted, 1)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].pattern_type, "recurring_unavailable_slot")
        self.assertEqual(patterns[0].key, "recurring_unavailable_tuesday_evening")

    def test_run_memory_maintenance_archives_stale_maintenance_patterns(self) -> None:
        self.db.add(
            s.UserPattern(
                user_id=self.user.id,
                category="availability",
                pattern_type="recurring_unavailable_slot",
                key="recurring_unavailable_tuesday_evening",
                value="Mardi soir souvent complique.",
                source="maintenance",
                confidence=0.8,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="long",
                evidence_count=4,
                affects_json='["planning", "conversation"]',
                metadata_json="{}",
            )
        )
        self.db.commit()

        result = run_memory_maintenance(
            self.db,
            user_id=self.user.id,
            now=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result.patterns_archived, 1)
        self.assertEqual(len(repo.get_active_patterns(self.db, self.user.id, limit=12)), 0)


if __name__ == "__main__":
    unittest.main()
