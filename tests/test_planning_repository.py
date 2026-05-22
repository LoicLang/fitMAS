from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-planning-repo-", suffix=".db"))

from fitmas import schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.athlete.fitness_snapshot import FitnessSnapshot
from fitmas.domain.planning.planning_decision import PlanningDecision
from fitmas.domain.athlete.readiness import ReadinessState
from fitmas.domain.planning import repository as planning_repo


class PlanningRepositoryTest(unittest.TestCase):
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

    def test_planning_snapshots_round_trip(self) -> None:
        fitness = FitnessSnapshot(
            user_id=self.user.id,
            date=date(2026, 3, 22),
            ctl=41.0,
            atl=36.0,
            tsb=5.0,
            ramp_rate=0.04,
            weekly_target_tss=210.0,
            weekly_actual_tss=190.0,
            completion_rate_14d=0.79,
            key_sessions_done_14d=2,
            volume_sessions_done_14d=4,
            sport_ctl={"running": 32.0, "cycling": 0.0, "swimming": 9.0, "strength": 0.0, "climbing": 0.0},
            sport_volume_hours={"running": 4.1, "cycling": 0.0, "swimming": 1.0, "strength": 0.0, "climbing": 0.0},
        )
        readiness = ReadinessState(
            user_id=self.user.id,
            date=date(2026, 3, 22),
            physical="high",
            mental="high",
            logistical="clear",
            injury_risk="low",
            risk_flags=(),
            summary="Stable.",
        )
        decision = PlanningDecision(
            user_id=self.user.id,
            week_start=date(2026, 3, 16),
            decision_version="v1",
            planning_mode="increase_load",
            adaptation_level="low",
            adaptation_scope="week",
            weekly_target_tss=220.0,
            intensity_distribution="build",
            key_session_count=3,
            strength_session_count=1,
            long_session=True,
            rationale=("readiness haute",),
            adaptations=("ajouter un peu de charge",),
            risk_flags=(),
        )

        athlete_repo.save_fitness_snapshot(self.db, fitness)
        athlete_repo.save_readiness_snapshot(self.db, readiness)
        planning_repo.save_planning_decision(self.db, decision)

        saved_fitness = athlete_repo.to_domain_fitness_snapshot(
            athlete_repo.get_latest_fitness_snapshot_record(self.db, self.user.id)
        )
        saved_readiness = athlete_repo.to_domain_readiness_snapshot(
            athlete_repo.get_latest_readiness_snapshot_record(self.db, self.user.id)
        )
        saved_decision = planning_repo.to_domain_planning_decision(
            planning_repo.get_latest_planning_decision_record(self.db, self.user.id)
        )

        self.assertEqual(saved_fitness.weekly_target_tss, 210.0)
        self.assertEqual(saved_fitness.sport_ctl["running"], 32.0)
        self.assertEqual(saved_readiness.physical, "high")
        self.assertEqual(saved_decision.planning_mode, "increase_load")
        self.assertEqual(saved_decision.key_session_count, 3)


if __name__ == "__main__":
    unittest.main()
