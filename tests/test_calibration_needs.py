from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas.domain.coaching.calibration_needs import (
    CalibrationNeedType,
    build_resolution_memory_updates,
    detect_calibration_need,
    fallback_resolve_calibration_need,
)
from fitmas.domain.coaching.calibration_status import CalibrationPhase, CalibrationStatus
from fitmas.domain.planning.contract import AvailabilityConfidence, AvailabilityState


class CalibrationNeedsTest(unittest.TestCase):
    def test_detect_availability_need_for_upcoming_unknown_day(self) -> None:
        profile = AthleteProfileSnapshot(
            user_id=1,
            primary_sports=("running",),
            primary_sport="running",
            level_by_sport={"running": "intermediate"},
            goals=("reprendre",),
            weekly_availability={"tuesday": ("mardi matin fiable",)},
            equipment=(),
            constraints=(),
            preferences=(),
            preferred_training_times=("morning",),
            coach_tone="direct",
            coach_style_notes="",
            athlete_identity_summary="",
            onboarding_completed=True,
        )
        calibration_status = CalibrationStatus(
            phase=CalibrationPhase.DRAFT,
            label="First Week Draft",
            summary="draft",
            next_step="test",
            known_unknowns=("la vraie semaine",),
            days_since_start=2,
            activity_count_14d=1,
            pattern_count=0,
            adaptation_count_14d=0,
        )
        availability_state = AvailabilityState(
            confidence=AvailabilityConfidence.INFERRED,
            preferred_windows=(),
            constrained_days=(),
            equipment=(),
            preferred_training_times=("morning",),
            summary="partial",
        )
        need = detect_calibration_need(
            profile=profile,
            calibration_status=calibration_status,
            availability_state=availability_state,
            scheduled_sessions=[
                {
                    "id": 12,
                    "day": "thursday",
                    "scheduled_date": "2026-03-31",
                    "sport_type": "running",
                    "session_title": "Tempo",
                    "priority": "Seance cle",
                }
            ],
            memory_items=[],
            today=date(2026, 3, 29),
            source="heartbeat_morning",
            channel_hint="telegram",
            preferred_types=(CalibrationNeedType.AVAILABILITY_WINDOW,),
            now=datetime(2026, 3, 29, 8, 0, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(need)
        self.assertEqual(need.need_type, CalibrationNeedType.AVAILABILITY_WINDOW)
        self.assertEqual(need.topic, "availability:thursday")

    def test_fallback_resolution_and_memory_updates_for_availability(self) -> None:
        need = detect_calibration_need(
            profile=AthleteProfileSnapshot(
                user_id=1,
                primary_sports=("running",),
                primary_sport="running",
                level_by_sport={"running": "intermediate"},
                goals=("reprendre",),
                weekly_availability={},
                equipment=(),
                constraints=(),
                preferences=(),
                preferred_training_times=("morning",),
                coach_tone="direct",
                coach_style_notes="",
                athlete_identity_summary="",
                onboarding_completed=False,
            ),
            calibration_status=CalibrationStatus(
                phase=CalibrationPhase.DRAFT,
                label="First Week Draft",
                summary="draft",
                next_step="test",
                known_unknowns=("la vraie semaine",),
                days_since_start=1,
                activity_count_14d=0,
                pattern_count=0,
                adaptation_count_14d=0,
            ),
            availability_state=AvailabilityState(
                confidence=AvailabilityConfidence.SPARSE,
                preferred_windows=(),
                constrained_days=(),
                equipment=(),
                preferred_training_times=("morning",),
                summary="sparse",
            ),
            scheduled_sessions=[
                {
                    "id": 12,
                    "day": "thursday",
                    "scheduled_date": "2026-03-31",
                    "sport_type": "running",
                    "session_title": "Tempo",
                    "priority": "Seance cle",
                }
            ],
            memory_items=[],
            today=date(2026, 3, 29),
            source="heartbeat_morning",
            channel_hint="telegram",
            preferred_types=(CalibrationNeedType.AVAILABILITY_WINDOW,),
            now=datetime(2026, 3, 29, 8, 0, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(need)

        resolution = fallback_resolve_calibration_need("Plutot le soir", need)
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.normalized_value["windows"], ["evening"])

        updates = build_resolution_memory_updates(need, resolution)
        self.assertEqual(updates[0]["category"], "calibration_need")
        self.assertEqual(updates[0]["action"], "archive")
        self.assertEqual(updates[1]["category"], "availability")
        self.assertEqual(updates[1]["key"], "weekly_slot_thursday")


if __name__ == "__main__":
    unittest.main()
