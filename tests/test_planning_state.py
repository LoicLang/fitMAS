from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.planning import repository as planning_repo

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-planning-state-", suffix=".db"))

from fitmas import schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.domain.planning.planning_state import refresh_planning_state


class PlanningStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            objective="revenir fort",
            primary_objective="reprendre la course",
            weekly_structure_notes="Lundi piscine 7h. Jeudi matin dispo.",
            coach_style="strict",
            onboarding_status="completed",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        self.db.add_all(
            [
                s.UserSport(user_id=self.user.id, sport_type="running", priority_rank=0, level_note="intermediaire"),
                s.UserSport(user_id=self.user.id, sport_type="swimming", priority_rank=1, level_note="debutant"),
                s.UserConstraint(user_id=self.user.id, text="mollet fragile"),
                s.UserFact(
                    user_id=self.user.id,
                    category="availability",
                    key="thursday",
                    value="Jeudi matin libre",
                    source="onboarding",
                    confidence=1.0,
                    confirmed=True,
                    active=True,
                ),
                s.Activity(
                    user_id=self.user.id,
                    source="manual",
                    sport_type="running",
                    title="Footing facile",
                    duration_min=50,
                    started_at=datetime.fromisoformat("2026-03-20T07:00:00+01:00"),
                    tss=42.0,
                ),
                s.ScheduledSession(
                    user_id=self.user.id,
                    day="sunday",
                    label="Dimanche",
                    scheduled_date=datetime.fromisoformat("2026-03-22T00:00:00+01:00"),
                    sport_type="running",
                    session_type="long",
                    session_title="Sortie longue",
                    session_goal="Repere",
                    duration_min=70,
                    intensity="moderate",
                    load_score=3,
                    priority="Repere fort",
                    completion_status="planned",
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_refresh_planning_state_builds_and_persists_bundle(self) -> None:
        bundle = refresh_planning_state(
            self.db,
            user=self.user,
            as_of_date="2026-03-22",
            mesocycle_week=2,
        )

        self.assertEqual(bundle.profile.primary_sport, "running")
        self.assertEqual(bundle.fitness.date.isoformat(), "2026-03-22")
        self.assertIsNotNone(athlete_repo.get_latest_fitness_snapshot_record(self.db, self.user.id))
        self.assertIsNotNone(athlete_repo.get_latest_readiness_snapshot_record(self.db, self.user.id))
        self.assertIsNotNone(planning_repo.get_latest_planning_decision_record(self.db, self.user.id))
        self.assertIn(
            bundle.decision.planning_mode,
            {"maintain_load", "increase_load", "reduce_load", "restart_consistency", "tactical_adjustment", "injury_protection", "deload"},
        )


if __name__ == "__main__":
    unittest.main()
