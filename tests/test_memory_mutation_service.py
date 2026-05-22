from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-memory-service-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.core.db import Base, SessionLocal, engine, init_db
from fitmas.decision.command_actions import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
    HealthSignalAction,
    PreferenceSignalAction,
)
from fitmas.domain.execution.mutation_service import apply_execution_actions_for_user
from fitmas.domain.memory.mutation_service import apply_memory_actions_for_user
from fitmas.core.time_context import DAY_KEYS, day_label_fr


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
        self.assertEqual(len(result.event_ids), 2)
        self.assertEqual(tuple(event.id for event in events), result.event_ids)

    def test_memory_service_uses_canonical_sport_window_key_for_availability(self) -> None:
        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="natation impossible deux semaines",
                    availability="unavailable",
                    sport_type="natation",
                    starts_on="2026-05-01",
                    ends_on="2026-05-14",
                    confidence=0.91,
                    evidence="je ne peux pas nager deux semaines",
                ),
            ],
        )

        working = self.db.query(s.WorkingMemoryEntry).order_by(s.WorkingMemoryEntry.id).all()
        events = self.db.query(s.MemoryMutationEventRecord).order_by(s.MemoryMutationEventRecord.id).all()

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(working[0].key, "unavailable_swimming_2026-05-01_2026-05-14")
        self.assertIn("availability:unavailable_swimming_2026-05-01_2026-05-14", result.saved_keys)
        self.assertEqual(events[0].target_key, "unavailable_swimming_2026-05-01_2026-05-14")

    def test_available_action_resolves_overlapping_unavailability(self) -> None:
        start = datetime(2026, 5, 13)
        end = datetime(2026, 5, 14)
        self.db.add(
            s.WorkingMemoryEntry(
                user_id=self.user.id,
                category="availability",
                key="availability_2026-05-13_2026-05-14",
                value="unavailable: bloque par les inondations aujourd'hui et demain",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="short",
                scope="week",
                affects_json='["planning", "conversation"]',
                expires_at=datetime(2026, 5, 15),
                status="open",
                signal_kind="availability_unavailable",
                observed_at=start,
                valid_from=start,
                valid_until=datetime(2026, 5, 15),
                last_seen_at=start,
            )
        )
        self.db.commit()

        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="disponible demain",
                    availability="available",
                    starts_on="2026-05-14",
                    ends_on="2026-05-14",
                    confidence=0.92,
                    evidence="demain je suis dispo",
                ),
            ],
            now=datetime(2026, 5, 13, 17, 20),
        )

        self.db.expire_all()
        rows = self.db.query(s.WorkingMemoryEntry).order_by(s.WorkingMemoryEntry.id).all()
        old_unavailable = rows[0]

        self.assertEqual(result.applied_count, 1)
        self.assertFalse(old_unavailable.active)
        self.assertEqual(old_unavailable.status, "resolved")
        self.assertEqual(old_unavailable.resolution_reason, "availability_available_overlap")

    def test_available_action_resolves_legacy_unavailable_general_key(self) -> None:
        start = datetime(2026, 5, 13)
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="availability",
                key="unavailable_general_2026-05-13_2026-05-14",
                value="Bloque par les inondations aujourd'hui et demain.",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="short",
                affects_json='["planning", "conversation"]',
                expires_at=datetime(2026, 5, 15),
                status="open",
                signal_kind="availability_unavailable",
                observed_at=start,
                valid_from=start,
                valid_until=datetime(2026, 5, 15),
                last_seen_at=start,
            )
        )
        self.db.commit()

        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="disponible demain",
                    availability="available",
                    starts_on="2026-05-14",
                    ends_on="2026-05-14",
                    confidence=0.92,
                    evidence="demain je suis dispo",
                ),
            ],
            now=datetime(2026, 5, 13, 17, 20),
        )

        self.db.expire_all()
        old_unavailable = (
            self.db.query(s.UserFact)
            .filter(s.UserFact.key == "unavailable_general_2026-05-13_2026-05-14")
            .one()
        )

        self.assertEqual(result.applied_count, 1)
        self.assertFalse(old_unavailable.active)
        self.assertEqual(old_unavailable.status, "resolved")
        self.assertEqual(old_unavailable.resolution_reason, "availability_available_overlap")

    def test_available_action_resolves_legacy_unavailable_with_inclusive_end_of_day(self) -> None:
        start = datetime(2026, 5, 13)
        self.db.add(
            s.UserFact(
                user_id=self.user.id,
                category="availability",
                key="unavailable_general_2026-05-13_2026-05-14",
                value="Bloque par les inondations aujourd'hui et demain.",
                source="conversation",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="short",
                affects_json='["planning", "conversation"]',
                expires_at=datetime(2026, 5, 14, 23, 59),
                status="open",
                signal_kind="availability_unavailable",
                observed_at=start,
                valid_from=start,
                valid_until=datetime(2026, 5, 14, 23, 59),
                last_seen_at=start,
            )
        )
        self.db.commit()

        apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="disponible demain",
                    availability="available",
                    starts_on="2026-05-14",
                    ends_on="2026-05-14",
                    confidence=0.92,
                    evidence="demain je suis dispo",
                ),
            ],
            now=datetime(2026, 5, 13, 17, 20),
        )

        self.db.expire_all()
        old_unavailable = (
            self.db.query(s.UserFact)
            .filter(s.UserFact.key == "unavailable_general_2026-05-13_2026-05-14")
            .one()
        )

        self.assertFalse(old_unavailable.active)
        self.assertEqual(old_unavailable.status, "resolved")
        self.assertEqual(old_unavailable.resolution_reason, "availability_available_overlap")

    def test_memory_service_persists_health_lifecycle_for_readiness(self) -> None:
        now = datetime(2026, 5, 11, 8, 0)

        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                HealthSignalAction(
                    type="record_health_signal",
                    health_signal="tension tibia reglee",
                    body_area="tibia",
                    signal_kind="tension",
                    severity="mild",
                    status="resolved",
                    confidence=0.9,
                    evidence="plus de tension au tibia",
                ),
            ],
            now=now,
        )

        facts = self.db.query(s.UserFact).all()
        working = self.db.query(s.WorkingMemoryEntry).all()

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(facts, [])
        self.assertEqual(working[0].category, "health")
        self.assertEqual(working[0].key, "health_tibia")
        self.assertEqual(working[0].status, "resolved")
        self.assertEqual(working[0].severity, "mild")
        self.assertEqual(working[0].signal_kind, "tension")
        self.assertIn("readiness", working[0].affects_json)
        self.assertEqual(working[0].resolved_at, now)

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
        self.assertEqual(len(result.event_ids), 1)
        self.assertEqual(result.event_ids[0], events[0].id)

    def test_execution_service_resolves_iso_date_target_ref_from_typed_llm_action(self) -> None:
        session = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo 34min")

        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=[
                ExecutionUpdateAction(
                    type="record_execution_update",
                    target_ref=session.scheduled_date.date().isoformat(),
                    status="not_completed",
                    completed=False,
                    sport_type="strength",
                    confidence=0.95,
                    evidence="pas eu le temps hier",
                )
            ],
        )

        self.db.expire_all()
        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.blocked_count, 0)
        self.assertEqual(updated.completion_status, "skipped")

    def test_execution_service_resolves_embedded_iso_date_target_ref_from_typed_llm_action(self) -> None:
        session = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo 34min")

        for target_ref in (
            f"{session.scheduled_date.date().isoformat()} session: Renfo 34min",
            f"{session.scheduled_date.date().isoformat()}_Renfo_34min",
            f"Renfo 34min ({session.scheduled_date.date().isoformat()})",
        ):
            with self.subTest(target_ref=target_ref):
                repo.set_scheduled_session_status(self.db, session.id, "planned")
                result = apply_execution_actions_for_user(
                    self.db,
                    user=self.user,
                    actions=[
                        ExecutionUpdateAction(
                            type="record_execution_update",
                            target_ref=target_ref,
                            status="not_completed",
                            completed=False,
                            sport_type="strength",
                            confidence=0.95,
                            evidence="pas eu le temps hier",
                        )
                    ],
                )

                self.db.expire_all()
                updated = repo.get_scheduled_session(self.db, self.user.id, session.id)

                self.assertEqual(result.applied_count, 1)
                self.assertEqual(result.blocked_count, 0)
                self.assertEqual(updated.completion_status, "skipped")

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
        self.assertEqual(len(result.event_ids), 1)
        self.assertEqual(result.event_ids[0], events[0].id)

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
