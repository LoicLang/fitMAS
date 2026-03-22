from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-facts-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db


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
        self.assertEqual(row.ttl, "short")
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


if __name__ == "__main__":
    unittest.main()
