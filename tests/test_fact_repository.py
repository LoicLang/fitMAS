from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-facts-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db


class FactRepositoryTest(unittest.TestCase):
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

    def test_upsert_facts_persists_memory_metadata(self) -> None:
        saved = repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "fatigue",
                    "key": "legs_today",
                    "value": "Jambes lourdes aujourd'hui",
                    "confidence": 0.8,
                    "confirmed": True,
                    "source": "conversation",
                }
            ],
        )

        self.assertEqual(len(saved), 1)
        row = saved[0]
        self.assertEqual(row.urgency, "high")
        self.assertEqual(row.ttl, "immediate")
        self.assertIn("conversation", row.affects_json)
        self.assertIsNotNone(row.expires_at)

    def test_get_active_facts_filters_expired_rows(self) -> None:
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="constraint",
                key="old",
                value="old",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="short",
                affects_json='["planning"]',
                expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None),
            )
        )
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="preference",
                key="morning",
                value="Plutot le matin",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="low",
                ttl="long",
                affects_json='["planning"]',
                expires_at=None,
            )
        )
        self.db.commit()

        active = repo.get_active_facts(self.db, self.user.id, limit=12)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].key, "morning")

    def test_upsert_working_memory_keeps_short_lived_state_out_of_profile_memory(self) -> None:
        saved = repo.upsert_working_memory(
            self.db,
            self.user.id,
            [
                {
                    "category": "execution",
                    "key": "running_2026_03_29",
                    "value": "Course aujourd'hui 30 min",
                    "confidence": 0.85,
                    "confirmed": True,
                    "source": "conversation",
                    "ttl": "immediate",
                    "scope": "day",
                    "affects": ["conversation", "heartbeat"],
                }
            ],
        )

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].scope, "day")
        self.assertEqual(len(repo.get_active_facts(self.db, self.user.id, limit=12)), 0)
        active_memory = repo.get_active_memory_items(self.db, self.user.id, profile_limit=12, working_limit=12, total_limit=24)
        self.assertEqual(len(active_memory), 1)
        self.assertEqual(active_memory[0].category, "execution")

    def test_purge_expired_working_memory_archives_old_entries(self) -> None:
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
                expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None),
            )
        )
        self.db.commit()

        archived = repo.purge_expired_working_memory(self.db, self.user.id)

        self.assertEqual(archived, 1)
        self.assertEqual(len(repo.get_active_working_memory(self.db, self.user.id, limit=12)), 0)


if __name__ == "__main__":
    unittest.main()
