from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-planning-schema-", suffix=".db"))

from sqlalchemy import inspect

from fitmas.db import Base, engine, init_db


class PlanningPersistenceSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    def test_v2_planning_tables_exist(self) -> None:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        self.assertIn("fitness_snapshots", tables)
        self.assertIn("readiness_snapshots", tables)
        self.assertIn("planning_decisions", tables)


if __name__ == "__main__":
    unittest.main()
